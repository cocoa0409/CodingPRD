"""Tour stops: logistics, the sales cycle, the safety cycle and the run order."""
from datetime import timedelta

from db import db, new_row, touch
from errors import fail
from middleware import (
    ROLE_COMPETITOR_TEAM,
    ROLE_FINANCE_CONTROLLER,
    ROLE_SAFETY_OFFICIAL,
    ROLE_SERIES_PROMOTER,
    ROLE_SPONSOR_REP,
    ROLE_TICKETING_MANAGER,
    ROLE_VENUE_MANAGER,
    auth,
    enum_filter,
    pagination,
    string_filter,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

SALES_STATES = (
    "SALES_PENDING",
    "ON_SALE",
    "SALES_HALTED",
    "SALES_CLOSED",
    "SETTLED",
    "CANCELLED",
)
SEGMENT_TYPES = ("COMPETITION", "INTERMISSION")


def _chain_link_invalid(stop, preceding_stop):
    """The four conditions of PRD 3.2 that make a `preceding_stop_id` link invalid."""
    if preceding_stop is None:
        return False
    if preceding_stop["id"] == stop["id"]:
        return True
    if preceding_stop["season_id"] != stop["season_id"]:
        return True
    if validate.parse_date(preceding_stop["event_date"]) >= validate.parse_date(
        stop["event_date"]
    ):
        return True
    for other in db.stops.values():
        if other["id"] == stop["id"]:
            continue
        if other["preceding_stop_id"] == preceding_stop["id"]:
            return True
    return False


def _commit_timeline(stop, segments):
    """Recompute the whole timeline; each segment whose figures move is bumped."""
    assignments, end_offset = calc.run_order_timeline(segments)
    for segment in segments:
        values = assignments[segment["id"]]
        changed = any(segment.get(key) != value for key, value in values.items())
        segment.update(values)
        if changed and segment.get("_fresh") is not True:
            touch(segment)
    return end_offset


def register(app):
    # ------------------------------------------------------------- stop reads
    @app.route("/tour-stops", methods=["GET"])
    def list_stops():
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_VENUE_MANAGER,
            ROLE_TICKETING_MANAGER,
            ROLE_SAFETY_OFFICIAL,
            ROLE_FINANCE_CONTROLLER,
            ROLE_COMPETITOR_TEAM,
        )
        limit, offset = pagination()
        season_id = string_filter("season_id")
        booking_id = string_filter("venue_booking_id")
        preceding_id = string_filter("preceding_stop_id")
        market_code = string_filter("market_code")
        sales_state = enum_filter("sales_state", SALES_STATES)
        rows = derive.all_stops()
        if season_id is not None:
            rows = [r for r in rows if r["season_id"] == season_id]
        if booking_id is not None:
            rows = [r for r in rows if r["venue_booking_id"] == booking_id]
        if preceding_id is not None:
            rows = [r for r in rows if r["preceding_stop_id"] == preceding_id]
        if market_code is not None:
            rows = [r for r in rows if r["market_code"] == market_code]
        if sales_state is not None:
            rows = [r for r in rows if r["sales_state"] == sales_state]
        return list_response([serialize.stop(r) for r in rows], limit, offset)

    @app.route("/tour-stops/<stop_id>", methods=["GET"])
    def read_stop(stop_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_VENUE_MANAGER,
            ROLE_TICKETING_MANAGER,
            ROLE_SAFETY_OFFICIAL,
            ROLE_FINANCE_CONTROLLER,
            ROLE_COMPETITOR_TEAM,
            ROLE_SPONSOR_REP,
        )
        return object_response(serialize.stop(derive.get_stop(stop_id)))

    # --------------------------------------------------------------- logistics
    @app.route("/tour-stops/<stop_id>/logistics", methods=["PATCH"])
    def patch_logistics(stop_id):
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        doors_raw, _doors_dt = validate.field_datetime(payload, "doors_open_utc", required=False)
        show_raw, _show_dt = validate.field_datetime(payload, "show_start_utc", required=False)
        window = validate.field_int(payload, "show_window_minutes", required=False, minimum=0)
        pit_price = validate.field_int(payload, "pit_party_price_cents", required=False, minimum=0)
        pit_capacity = validate.field_int(payload, "pit_party_capacity", required=False, minimum=0)
        haul = validate.field_int(payload, "haul_distance_miles", required=False, minimum=0)
        preceding_supplied = validate.supplied(payload, "preceding_stop_id")
        preceding_id = validate.field_id(payload, "preceding_stop_id", required=False)

        stop = derive.get_stop(stop_id)
        preceding_stop = None
        if preceding_id is not None:
            preceding_stop = derive.get_stop(preceding_id)

        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        booking = derive.booking_of_stop(stop)
        effective_doors = doors_raw if doors_raw is not None else stop["doors_open_utc"]
        effective_show = show_raw if show_raw is not None else stop["show_start_utc"]
        effective_haul = haul if haul is not None else stop["haul_distance_miles"]
        if preceding_supplied:
            effective_preceding = preceding_stop
        elif stop["preceding_stop_id"] is not None:
            effective_preceding = db.stops.get(stop["preceding_stop_id"])
        else:
            effective_preceding = None

        # 31 — the one-sided transport buffer. The buffer is anchored on the
        # predecessor's tear-down, so it is only meaningful once the link itself is a
        # well-formed one; a structurally invalid link falls through to rule 38 below
        # instead of reporting a buffer violation computed against a bogus anchor.
        link_invalid = _chain_link_invalid(stop, effective_preceding)
        if (
            (preceding_supplied or haul is not None)
            and effective_preceding is not None
            and not link_invalid
        ):
            preceding_booking = derive.booking_of_stop(effective_preceding)
            earliest = calc.earliest_load_in(preceding_booking, effective_haul)
            if calc.dt(booking["load_in_start_utc"]) < earliest:
                fail("ERR_HAUL_BUFFER_VIOLATION")

        # 35 — the show timing triple
        if effective_show is not None:
            show_dt = calc.dt(effective_show)
            if effective_doors is not None:
                doors_dt = calc.dt(effective_doors)
                if doors_dt >= show_dt:
                    fail("ERR_SHOW_TIMING_INVALID")
                if show_dt - doors_dt < timedelta(hours=1):
                    fail("ERR_SHOW_TIMING_INVALID")
            if show_dt < calc.dt(booking["load_in_start_utc"]) or show_dt > calc.dt(
                booking["tear_down_end_utc"]
            ):
                fail("ERR_SHOW_TIMING_INVALID")

        # 38 — rotation chain validity
        if preceding_stop is not None and _chain_link_invalid(stop, preceding_stop):
            fail("ERR_ROTATION_CHAIN_INVALID")

        if doors_raw is not None:
            stop["doors_open_utc"] = doors_raw
        if show_raw is not None:
            stop["show_start_utc"] = show_raw
        if window is not None:
            stop["show_window_minutes"] = window
        if pit_price is not None:
            stop["pit_party_price_cents"] = pit_price
        if pit_capacity is not None:
            stop["pit_party_capacity"] = pit_capacity
        if haul is not None:
            stop["haul_distance_miles"] = haul
        if preceding_supplied:
            stop["preceding_stop_id"] = preceding_id
        touch(stop)

        if show_raw is not None:
            _commit_timeline(stop, derive.segments_of_stop(stop["id"]))
        flow.apply_posture(stop)
        return object_response(serialize.stop(stop))

    # ------------------------------------------------------------ sales cycle
    @app.route("/tour-stops/<stop_id>/on-sale", methods=["POST"])
    def on_sale(stop_id):
        auth(ROLE_TICKETING_MANAGER)
        validate.body()
        stop = derive.get_stop(stop_id)
        flow.ensure_season_open(derive.season_of_stop(stop))
        if stop["sales_state"] != "SALES_PENDING":
            fail("ERR_INVALID_STATE_TRANSITION")
        flow.ensure_not_frozen(stop)
        if stop["safety_state"] != "SAFETY_CERTIFIED":
            fail("ERR_SAFETY_NOT_CERTIFIED")
        if derive.stop_competition_segment_count(stop) < 1:
            fail("ERR_RUN_ORDER_INCOMPLETE")
        if not derive.tiers_of_stop(stop["id"]):
            fail("ERR_NO_TICKET_TIERS")
        if flow.posture(stop) != "OPEN":
            fail("ERR_STOP_NOT_READY")
        stop["sales_state"] = "ON_SALE"
        touch(stop)
        return object_response(serialize.stop(stop))

    @app.route("/tour-stops/<stop_id>/close-sales", methods=["POST"])
    def close_sales(stop_id):
        auth(ROLE_TICKETING_MANAGER)
        validate.body()
        stop = derive.get_stop(stop_id)
        flow.ensure_season_open(derive.season_of_stop(stop))
        if stop["sales_state"] not in ("ON_SALE", "SALES_HALTED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        stop["sales_state"] = "SALES_CLOSED"
        flow.void_pending_orders(stop, "SALES_CLOSED")
        touch(stop)
        return object_response(serialize.stop(stop))

    @app.route("/tour-stops/<stop_id>/resume-sales", methods=["POST"])
    def resume_sales(stop_id):
        auth(ROLE_TICKETING_MANAGER)
        validate.body()
        stop = derive.get_stop(stop_id)
        flow.ensure_season_open(derive.season_of_stop(stop))
        if stop["sales_state"] != "SALES_HALTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        flow.ensure_not_frozen(stop)
        if stop["safety_state"] != "SAFETY_CERTIFIED":
            fail("ERR_SAFETY_NOT_CERTIFIED")
        if flow.posture(stop) != "OPEN":
            fail("ERR_STOP_NOT_READY")
        stop["sales_state"] = "ON_SALE"
        touch(stop)
        return object_response(serialize.stop(stop))

    # ----------------------------------------------------------- safety cycle
    @app.route("/tour-stops/<stop_id>/safety-suspend", methods=["POST"])
    def safety_suspend(stop_id):
        auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        validate.field_string(payload, "reason")
        stop = derive.get_stop(stop_id)
        flow.ensure_stop_writable(stop)
        if stop["safety_state"] != "SAFETY_CERTIFIED":
            fail("ERR_INVALID_STATE_TRANSITION")
        stop["safety_state"] = "SAFETY_SUSPENDED"
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.stop(stop))

    @app.route("/tour-stops/<stop_id>/safety-reinstate", methods=["POST"])
    def safety_reinstate(stop_id):
        auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        validate.field_string(payload, "note", required=False)
        stop = derive.get_stop(stop_id)
        flow.ensure_stop_writable(stop)
        plan = derive.plan_of_stop(stop["id"])
        if (
            stop["safety_state"] != "SAFETY_SUSPENDED"
            or plan is None
            or plan["state"] != "CERTIFIED"
        ):
            fail("ERR_INVALID_STATE_TRANSITION")
        stop["safety_state"] = "SAFETY_CERTIFIED"
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.stop(stop))

    # -------------------------------------------------------------- run order
    @app.route("/tour-stops/<stop_id>/show-segments", methods=["POST"])
    def create_segment(stop_id):
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        segment_type = validate.field_enum(payload, "segment_type", SEGMENT_TYPES)
        title = validate.field_string(payload, "title")
        position = validate.field_int(payload, "run_order_position", minimum=1)
        duration = validate.field_int(payload, "duration_minutes", minimum=1)
        featured_id = validate.field_id(payload, "featured_vehicle_entry_id", required=False)

        stop = derive.get_stop(stop_id)
        featured = None
        if featured_id is not None:
            featured = derive.get_entry(featured_id)

        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        if featured is not None:
            if featured["tech_status"] == "TECH_HELD":
                fail("ERR_ENTRY_TECH_HELD")
            if featured["tour_stop_id"] != stop["id"]:
                fail("ERR_CHILD_STOP_MISMATCH")

        existing = derive.segments_of_stop(stop["id"])
        for other in existing:
            if other["run_order_position"] == position:
                fail("ERR_SEGMENT_TIMELINE_CONFLICT")

        row = new_row(
            tour_stop_id=stop["id"],
            featured_vehicle_entry_id=featured_id,
            segment_type=segment_type,
            title=title,
            run_order_position=position,
            duration_minutes=duration,
            start_offset_minutes=0,
            end_offset_minutes=0,
            reset_gap_minutes=0,
        )
        row["_fresh"] = True
        prospective = existing + [row]
        assignments, end_offset = calc.run_order_timeline(prospective)
        if end_offset > stop["show_window_minutes"]:
            fail("ERR_SHOW_WINDOW_EXCEEDED")

        db.segments[row["id"]] = row
        _commit_timeline(stop, prospective)
        del row["_fresh"]
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.segment(row), 201)

    @app.route("/tour-stops/<stop_id>/show-segments", methods=["GET"])
    def list_segments(stop_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_TICKETING_MANAGER,
            ROLE_SAFETY_OFFICIAL,
            ROLE_SPONSOR_REP,
        )
        limit, offset = pagination()
        stop = derive.get_stop(stop_id)
        rows = sorted(
            derive.segments_of_stop(stop["id"]), key=lambda s: s["run_order_position"]
        )
        return list_response([serialize.segment(r) for r in rows], limit, offset)

    @app.route("/show-segments/<segment_id>", methods=["GET"])
    def read_segment(segment_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_TICKETING_MANAGER,
            ROLE_SAFETY_OFFICIAL,
            ROLE_SPONSOR_REP,
        )
        return object_response(serialize.segment(derive.get_segment(segment_id)))
