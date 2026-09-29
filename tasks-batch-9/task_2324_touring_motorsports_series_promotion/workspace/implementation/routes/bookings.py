"""Venue bookings: proposal, negotiation, acceptance and withdrawal (PRD 3.1)."""
from db import clock_raw, db, new_row, touch
from errors import fail
from middleware import (
    ROLE_FINANCE_CONTROLLER,
    ROLE_SERIES_PROMOTER,
    ROLE_VENUE_MANAGER,
    auth,
    enum_filter,
    pagination,
    string_filter,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

BOOKING_STATES = ("TERMS_PROPOSED", "COUNTERED", "CONFIRMED", "WITHDRAWN")


def _check_occupancy(venue, booking_id, load_in_dt, tear_down_dt):
    if load_in_dt >= tear_down_dt:
        fail("ERR_VENUE_DATE_CONFLICT", "load_in_start_utc must precede tear_down_end_utc")
    others = [
        b
        for b in db.bookings.values()
        if b["venue_id"] == venue["id"] and b["state"] == "CONFIRMED" and b["id"] != booking_id
    ]
    if calc.occupancy_conflict(venue, load_in_dt, tear_down_dt, others):
        fail("ERR_VENUE_DATE_CONFLICT")


def _check_rotation(season, venue, booking_id, tour_date):
    other_dates = []
    for other in db.bookings.values():
        if other["season_id"] != season["id"] or other["id"] == booking_id:
            continue
        if other["state"] != "CONFIRMED":
            continue
        other_venue = db.venues[other["venue_id"]]
        if other_venue["market_code"] != venue["market_code"]:
            continue
        other_dates.append(validate.parse_date(other["tour_date"]))
    if calc.rotation_conflict(season, tour_date, other_dates):
        fail("ERR_MARKET_ROTATION_COOLDOWN")


def _terms(payload):
    """Shared body shape of counter and revise."""
    rental = validate.field_int(payload, "rental_base_cents", minimum=0)
    share = validate.field_number(payload, "revenue_share_pct", minimum=0, maximum=1)
    fee = validate.field_int(payload, "per_ticket_facility_fee_cents", minimum=0)
    load_in_raw, load_in_dt = validate.field_datetime(
        payload, "load_in_start_utc", required=False
    )
    tear_down_raw, tear_down_dt = validate.field_datetime(
        payload, "tear_down_end_utc", required=False
    )
    validate.field_string(payload, "note", required=False)
    return rental, share, fee, load_in_raw, tear_down_raw


def register(app):
    @app.route("/venue-bookings", methods=["POST"])
    def create_booking():
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        season_id = validate.field_id(payload, "season_id")
        venue_id = validate.field_id(payload, "venue_id")
        tour_date_raw, tour_date = validate.field_date(payload, "tour_date")
        rental = validate.field_int(payload, "rental_base_cents", minimum=0)
        share = validate.field_number(payload, "revenue_share_pct", minimum=0, maximum=1)
        fee = validate.field_int(payload, "per_ticket_facility_fee_cents", minimum=0)
        load_in_raw, load_in_dt = validate.field_datetime(payload, "load_in_start_utc")
        tear_down_raw, tear_down_dt = validate.field_datetime(payload, "tear_down_end_utc")

        season = derive.get_season(season_id)
        venue = derive.get_venue(venue_id)
        flow.ensure_season_open(season)

        season_start = validate.parse_date(season["season_start_date"])
        season_end = validate.parse_date(season["season_end_date"])
        if tour_date < season_start or tour_date > season_end:
            fail("ERR_DATE_OUTSIDE_SEASON")
        if (tour_date - db.clock_dt.date()).days < calc.BOOKING_LEAD_TIME_DAYS:
            fail("ERR_BOOKING_LEAD_TIME")
        _check_occupancy(venue, None, load_in_dt, tear_down_dt)
        _check_rotation(season, venue, None, tour_date)

        row = new_row(
            season_id=season["id"],
            venue_id=venue["id"],
            tour_date=tour_date_raw,
            rental_base_cents=rental,
            revenue_share_pct=share,
            per_ticket_facility_fee_cents=fee,
            load_in_start_utc=load_in_raw,
            tear_down_end_utc=tear_down_raw,
            state="TERMS_PROPOSED",
            negotiation_round=1,
            terms_source="PROMOTER",
            last_counter_by_user_id=None,
            confirmed_at=None,
            withdraw_reason=None,
        )
        db.bookings[row["id"]] = row
        touch(season)  # booking_count rose
        return object_response(serialize.booking(row), 201)

    @app.route("/venue-bookings", methods=["GET"])
    def list_bookings():
        auth(ROLE_SERIES_PROMOTER, ROLE_VENUE_MANAGER, ROLE_FINANCE_CONTROLLER)
        limit, offset = pagination()
        season_id = string_filter("season_id")
        venue_id = string_filter("venue_id")
        state = enum_filter("state", BOOKING_STATES)
        rows = derive.all_bookings()
        if season_id is not None:
            rows = [r for r in rows if r["season_id"] == season_id]
        if venue_id is not None:
            rows = [r for r in rows if r["venue_id"] == venue_id]
        if state is not None:
            rows = [r for r in rows if r["state"] == state]
        return list_response([serialize.booking(r) for r in rows], limit, offset)

    @app.route("/venue-bookings/<booking_id>", methods=["GET"])
    def read_booking(booking_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_VENUE_MANAGER, ROLE_FINANCE_CONTROLLER)
        return object_response(serialize.booking(derive.get_booking(booking_id)))

    @app.route("/venue-bookings/<booking_id>/counter", methods=["POST"])
    def counter_booking(booking_id):
        user_id, _role = auth(ROLE_VENUE_MANAGER)
        payload = validate.body()
        rental, share, fee, load_in_raw, tear_down_raw = _terms(payload)
        booking = derive.get_booking(booking_id)
        if user_id != booking["venue_id"]:
            fail("ERR_OWNERSHIP_MISMATCH")
        season = db.seasons[booking["season_id"]]
        flow.ensure_season_open(season)
        # PRD 2.10 item 11: the state error covers "a booking that is not
        # TERMS_PROPOSED or COUNTERED when countered, revised or accepted", so a
        # COUNTERED booking clears the state rung and falls through to the round cap.
        if booking["state"] not in ("TERMS_PROPOSED", "COUNTERED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        if booking["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

        booking["rental_base_cents"] = rental
        booking["revenue_share_pct"] = share
        booking["per_ticket_facility_fee_cents"] = fee
        if load_in_raw is not None:
            booking["load_in_start_utc"] = load_in_raw
        if tear_down_raw is not None:
            booking["tear_down_end_utc"] = tear_down_raw
        booking["terms_source"] = "VENUE"
        booking["last_counter_by_user_id"] = user_id
        booking["negotiation_round"] += 1
        booking["state"] = "COUNTERED"
        touch(booking)
        return object_response(serialize.booking(booking))

    @app.route("/venue-bookings/<booking_id>/revise", methods=["POST"])
    def revise_booking(booking_id):
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        rental, share, fee, load_in_raw, tear_down_raw = _terms(payload)
        booking = derive.get_booking(booking_id)
        season = db.seasons[booking["season_id"]]
        flow.ensure_season_open(season)
        if booking["state"] != "COUNTERED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if booking["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

        booking["rental_base_cents"] = rental
        booking["revenue_share_pct"] = share
        booking["per_ticket_facility_fee_cents"] = fee
        if load_in_raw is not None:
            booking["load_in_start_utc"] = load_in_raw
        if tear_down_raw is not None:
            booking["tear_down_end_utc"] = tear_down_raw
        booking["terms_source"] = "PROMOTER"
        booking["state"] = "TERMS_PROPOSED"
        touch(booking)
        return object_response(serialize.booking(booking))

    @app.route("/venue-bookings/<booking_id>/accept", methods=["POST"])
    def accept_booking(booking_id):
        auth(ROLE_SERIES_PROMOTER)
        validate.body()
        booking = derive.get_booking(booking_id)
        season = db.seasons[booking["season_id"]]
        venue = db.venues[booking["venue_id"]]
        flow.ensure_season_open(season)
        if booking["state"] not in ("TERMS_PROPOSED", "COUNTERED"):
            fail("ERR_INVALID_STATE_TRANSITION")

        _check_occupancy(
            venue,
            booking["id"],
            calc.dt(booking["load_in_start_utc"]),
            calc.dt(booking["tear_down_end_utc"]),
        )
        _check_rotation(season, venue, booking["id"], validate.parse_date(booking["tour_date"]))

        booking["state"] = "CONFIRMED"
        booking["confirmed_at"] = clock_raw()
        touch(booking)

        stop = new_row(
            season_id=booking["season_id"],
            venue_booking_id=booking["id"],
            preceding_stop_id=None,
            market_code=venue["market_code"],
            event_date=booking["tour_date"],
            doors_open_utc=None,
            show_start_utc=None,
            show_window_minutes=150,
            pit_party_price_cents=2450,
            pit_party_capacity=0,
            sales_state="SALES_PENDING",
            safety_state="SAFETY_DRAFT",
            haul_distance_miles=0,
            cancel_reason=None,
        )
        db.stops[stop["id"]] = stop
        return object_response(serialize.booking(booking))

    @app.route("/venue-bookings/<booking_id>/withdraw", methods=["POST"])
    def withdraw_booking(booking_id):
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        reason = validate.field_string(payload, "reason")
        booking = derive.get_booking(booking_id)
        season = db.seasons[booking["season_id"]]
        flow.ensure_season_open(season)
        if booking["state"] not in ("TERMS_PROPOSED", "COUNTERED", "CONFIRMED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        if booking["state"] == "CONFIRMED":
            stop = derive.stop_of_booking(booking["id"])
            if stop is not None and stop["sales_state"] == "SETTLED":
                fail("ERR_INVALID_STATE_TRANSITION")
        flow.cascade_a(booking, reason)
        return object_response(serialize.booking(booking))
