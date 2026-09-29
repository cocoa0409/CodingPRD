"""Offer negotiation: draft, issue, counter, revise, accept, decline, sweep."""

from datetime import timedelta

from flask import Blueprint, g

from db import db, iso_instant, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint, is_artist_rep, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    body_fk,
    date_str,
    load,
    opt_enum,
    opt_id,
    opt_instant,
    opt_int,
    opt_string,
    pagination,
    query_enum,
    query_string,
    req_date,
    req_instant,
    req_int,
    req_string,
    stored_date,
    stored_instant,
)

bp = Blueprint("offers", __name__)

OFFER_STATUSES = (
    "DRAFT",
    "ISSUED",
    "COUNTERED",
    "ACCEPTED",
    "DECLINED",
    "EXPIRED",
    "SUPERSEDED",
)
EXCLUSIVITY_SCOPES = ("FULL", "TICKETED_ONLY", "FESTIVAL_ONLY")
READ_ROLES = ["TalentBuyer", "ArtistRep", "BusinessAffairs", "FinanceController"]


# --------------------------------------------------------------------------- #
# helpers shared by the negotiation gates
# --------------------------------------------------------------------------- #
def _slot_end(slot_start, set_length_minutes):
    return slot_start + timedelta(minutes=set_length_minutes)


def _check_event_window(festival, slot_start, slot_end):
    start_date = stored_date(festival["event_start_date"])
    end_date = stored_date(festival["event_end_date"])
    if not (start_date <= slot_start.date() <= end_date):
        fail("ERR_SLOT_OUTSIDE_EVENT_WINDOW", "slot start falls outside the event window")
    if not (start_date <= slot_end.date() <= end_date):
        fail("ERR_SLOT_OUTSIDE_EVENT_WINDOW", "slot end falls outside the event window")


def _check_radius_window(festival, window_start, window_end):
    if window_end < window_start:
        fail("ERR_RADIUS_WINDOW_INVALID", "window_end_date precedes window_start_date")
    event_start = stored_date(festival["event_start_date"])
    for endpoint_date in (window_start, window_end):
        if abs((endpoint_date - event_start).days) > calc.RADIUS_WINDOW_MAX_DAYS:
            fail(
                "ERR_RADIUS_WINDOW_INVALID",
                "radius window endpoints must lie within 365 days of the event start",
            )


def _check_not_expired(offer):
    if db.clock >= stored_instant(offer["offer_expires_utc"]):
        fail("ERR_OFFER_EXPIRED", "the logical clock has reached offer_expires_utc")


def _check_posture(festival):
    if festival["lineup_posture"] == "FROZEN":
        fail("ERR_LINEUP_FROZEN", "the edition's lineup is frozen")


def _check_risk(artist):
    if artist["adjudicated_risk_score"] >= calc.RISK_BLOCK_THRESHOLD:
        fail("ERR_ARTIST_RISK_BLOCKED", "the act's adjudicated risk score blocks offers")


def _check_stage_interval(stage, slot_start, slot_end, offer_id):
    if calc.stage_interval_conflict(stage, slot_start, slot_end, offer_id):
        fail("ERR_STAGE_SLOT_CONFLICT", "a buffered interval collision exists")


def _check_curfew(stage, slot_start, slot_end):
    if calc.curfew_minute_of(slot_start, slot_end) > stage["daily_curfew_minute"]:
        fail("ERR_CURFEW_EXCEEDED", "the set ends after the stage curfew")


def _check_day_load(stage, slot_start, set_length_minutes, offer_id):
    load_minutes = calc.stage_day_load(stage, slot_start, set_length_minutes, offer_id)
    if load_minutes > stage["daily_program_minutes_cap"]:
        fail("ERR_STAGE_DAY_CAP_EXCEEDED", "the stage day programming cap is exceeded")


def _check_billing_position(stage, slot_start, billing_position, offer_id):
    if calc.billing_position_taken(
        stage["id"], slot_start.date(), billing_position, offer_id
    ):
        fail("ERR_BILLING_POSITION_TAKEN", "the billing position is already held")


def _check_flagship(stage, billing_position):
    if billing_position == 1 and not stage["is_flagship"]:
        fail("ERR_HEADLINER_STAGE_REQUIRED", "a top-billed offer needs a flagship stage")


def _check_genre_cap(festival, artist, offer):
    share = calc.genre_committed_share(
        festival, artist["primary_genre"], offer, include_evaluated=True
    )
    if share > calc.GENRE_CAP:
        fail("ERR_GENRE_CAP_EXCEEDED", "the projected genre share exceeds the cap")


def _check_ceiling(festival, tier, artist, offer):
    ceiling, factor = calc.guarantee_ceiling(festival, tier, artist, offer)
    if offer["guarantee_cents"] + offer["production_fee_cents"] > ceiling:
        fail(
            "ERR_GUARANTEE_CEILING_EXCEEDED",
            "guarantee plus production fee exceeds the ceiling",
        )
    return ceiling, factor


# --------------------------------------------------------------------------- #
# POST /offers - drafting
# --------------------------------------------------------------------------- #
@bp.post("/offers")
@endpoint(["TalentBuyer"])
def create_offer():
    payload = body()
    req_string(payload, "festival_id", 1)
    req_string(payload, "artist_id", 1)
    req_string(payload, "budget_tier_id", 1)
    req_string(payload, "stage_id", 1)
    guarantee_cents = req_int(payload, "guarantee_cents", 0, None)
    billing_position = req_int(payload, "billing_position", 1, 200)
    set_length_minutes = req_int(payload, "set_length_minutes", 20, 180)
    slot_start = req_instant(payload, "slot_start_utc")
    offer_expires = req_instant(payload, "offer_expires_utc")
    radius_miles = opt_int(payload, "radius_miles", None, 0, 500)
    window_start = req_date(payload, "window_start_date")
    window_end = req_date(payload, "window_end_date")
    production_fee_cents = opt_int(payload, "production_fee_cents", 0, 0, None)
    exclusivity_scope = opt_enum(payload, "exclusivity_scope", EXCLUSIVITY_SCOPES, "FULL")
    waiver_fee_offer_cents = opt_int(payload, "waiver_fee_offer_cents", 0, 0, None)
    if "replaces_booking_id" in payload and payload["replaces_booking_id"] is not None:
        req_string(payload, "replaces_booking_id", 1)

    festival = body_fk(payload, "festival_id", "festivals")
    artist = body_fk(payload, "artist_id", "artists")
    tier = body_fk(payload, "budget_tier_id", "budget_tiers")
    stage = body_fk(payload, "stage_id", "stages")
    replaced = body_fk(payload, "replaces_booking_id", "bookings", required=False)

    if tier["festival_id"] != festival["id"] or stage["festival_id"] != festival["id"]:
        fail("ERR_FESTIVAL_MISMATCH", "the tier and stage must belong to the edition")

    if replaced is not None:
        if (
            replaced["festival_id"] != festival["id"]
            or replaced["contract_status"] != "CANCELLED"
        ):
            fail(
                "ERR_REPLACEMENT_TARGET_NOT_CANCELLED",
                "a replacement offer must point at a cancelled booking of this edition",
            )

    slot_end = _slot_end(slot_start, set_length_minutes)
    _check_event_window(festival, slot_start, slot_end)
    _check_radius_window(festival, window_start, window_end)

    if radius_miles is None:
        radius_miles = artist["default_radius_miles"]

    offer = new_row(
        festival_id=festival["id"],
        artist_id=artist["id"],
        budget_tier_id=tier["id"],
        stage_id=stage["id"],
        replaces_booking_id=replaced["id"] if replaced is not None else None,
        guarantee_cents=guarantee_cents,
        production_fee_cents=production_fee_cents,
        billing_position=billing_position,
        set_length_minutes=set_length_minutes,
        slot_start_utc=iso_instant(slot_start),
        slot_end_utc=iso_instant(slot_end),
        offer_expires_utc=iso_instant(offer_expires),
        status="DRAFT",
        round_number=0,
        counter_guarantee_cents=None,
        counter_billing_position=None,
        counter_set_length_minutes=None,
        counter_note=None,
        guarantee_ceiling_cents=0,
        genre_balance_factor=1.0,
        issued_by_user_id=None,
    )
    db.offers[offer["id"]] = offer

    clause = new_row(
        offer_id=offer["id"],
        booking_id=None,
        artist_id=artist["id"],
        radius_miles=radius_miles,
        window_start_date=date_str(window_start),
        window_end_date=date_str(window_end),
        exclusivity_scope=exclusivity_scope,
        enforcement_status="PROVISIONAL",
        waiver_status="NONE",
        waiver_competing_performance_id=None,
        waiver_fee_offer_cents=waiver_fee_offer_cents,
        waiver_fee_cents=0,
        breach_count=0,
    )
    db.radius_clauses[clause["id"]] = clause
    return respond_object(public(offer), 201)


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
@bp.get("/offers/<offer_id>")
@endpoint(READ_ROLES)
def get_offer(offer_id):
    offer = load("offers", offer_id)
    require_artist_scope(offer["artist_id"])
    return respond_object(public(offer))


@bp.get("/offers")
@endpoint(READ_ROLES)
def list_offers():
    status = query_enum("status", OFFER_STATUSES)
    festival_id = query_string("festival_id")
    artist_id = query_string("artist_id")
    budget_tier_id = query_string("budget_tier_id")
    stage_id = query_string("stage_id")
    replaces_booking_id = query_string("replaces_booking_id")
    limit, offset = pagination()

    rows = list(db.offers.values())
    if is_artist_rep():
        rows = [r for r in rows if r["artist_id"] == g.user_id]
    if festival_id is not None:
        rows = [r for r in rows if r["festival_id"] == festival_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if budget_tier_id is not None:
        rows = [r for r in rows if r["budget_tier_id"] == budget_tier_id]
    if stage_id is not None:
        rows = [r for r in rows if r["stage_id"] == stage_id]
    if replaces_booking_id is not None:
        rows = [r for r in rows if r["replaces_booking_id"] == replaces_booking_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = calc.sorted_rows(rows, [("slot_start_utc", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


# --------------------------------------------------------------------------- #
# POST /offers/{id}/issue
# --------------------------------------------------------------------------- #
@bp.post("/offers/<offer_id>/issue")
@endpoint(["TalentBuyer"])
def issue_offer(offer_id):
    offer = load("offers", offer_id)
    if offer["status"] != "DRAFT":
        fail("ERR_OFFER_NOT_NEGOTIABLE", "only a DRAFT offer may be issued")

    festival = db.festivals[offer["festival_id"]]
    tier = db.budget_tiers[offer["budget_tier_id"]]
    stage = db.stages[offer["stage_id"]]
    artist = db.artists[offer["artist_id"]]
    slot_start = stored_instant(offer["slot_start_utc"])
    slot_end = _slot_end(slot_start, offer["set_length_minutes"])

    _check_posture(festival)
    if not festival["tiers_allocated"]:
        fail("ERR_TIERS_NOT_ALLOCATED", "the budget waterfall has not been run")
    _check_risk(artist)
    _check_stage_interval(stage, slot_start, slot_end, offer["id"])
    _check_curfew(stage, slot_start, slot_end)
    _check_day_load(stage, slot_start, offer["set_length_minutes"], offer["id"])
    if calc.artist_double_booked(
        festival["id"], artist["id"], slot_start.date(), offer["id"]
    ):
        fail("ERR_ARTIST_DOUBLE_BOOKED", "the act is already committed on that date")
    _check_billing_position(stage, slot_start, offer["billing_position"], offer["id"])
    if tier["status"] != "OPEN" or tier["slots_committed"] >= tier["max_slots"]:
        fail("ERR_TIER_CLOSED", "the budget tier is closed")
    _check_flagship(stage, offer["billing_position"])
    if offer["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "the negotiation round cap is reached")
    _check_genre_cap(festival, artist, offer)
    ceiling, factor = _check_ceiling(festival, tier, artist, offer)

    offer["status"] = "ISSUED"
    offer["round_number"] = offer["round_number"] + 1
    offer["guarantee_ceiling_cents"] = ceiling
    offer["genre_balance_factor"] = float(factor)
    offer["issued_by_user_id"] = g.user_id
    offer["slot_end_utc"] = iso_instant(slot_end)
    touch(offer)

    clause = calc.clause_for_offer(offer["id"])
    if clause is not None and clause["enforcement_status"] == "PROVISIONAL":
        clause["enforcement_status"] = "ACTIVE"
        touch(clause)
    return respond_object(public(offer))


# --------------------------------------------------------------------------- #
# POST /offers/{id}/counter
# --------------------------------------------------------------------------- #
@bp.post("/offers/<offer_id>/counter")
@endpoint(["ArtistRep"])
def counter_offer(offer_id):
    payload = body()
    counter_guarantee_cents = req_int(payload, "counter_guarantee_cents", 0, None)
    counter_billing_position = opt_int(payload, "counter_billing_position", None, 1, 200)
    counter_set_length_minutes = opt_int(
        payload, "counter_set_length_minutes", None, 20, 180
    )
    counter_note = opt_string(payload, "counter_note", None, 1, None)

    offer = load("offers", offer_id)
    require_artist_scope(offer["artist_id"])
    if offer["status"] != "ISSUED":
        fail("ERR_OFFER_NOT_NEGOTIABLE", "only an ISSUED offer may be countered")
    _check_not_expired(offer)

    offer["counter_guarantee_cents"] = counter_guarantee_cents
    offer["counter_billing_position"] = counter_billing_position
    offer["counter_set_length_minutes"] = counter_set_length_minutes
    offer["counter_note"] = counter_note
    offer["status"] = "COUNTERED"
    touch(offer)
    return respond_object(public(offer))


# --------------------------------------------------------------------------- #
# POST /offers/{id}/revise
# --------------------------------------------------------------------------- #
@bp.post("/offers/<offer_id>/revise")
@endpoint(["TalentBuyer"])
def revise_offer(offer_id):
    payload = body()
    guarantee_cents = req_int(payload, "guarantee_cents", 0, None)
    production_fee_cents = opt_int(payload, "production_fee_cents", None, 0, None)
    billing_position = opt_int(payload, "billing_position", None, 1, 200)
    set_length_minutes = opt_int(payload, "set_length_minutes", None, 20, 180)
    slot_start = opt_instant(payload, "slot_start_utc", None)
    offer_expires = opt_instant(payload, "offer_expires_utc", None)

    offer = load("offers", offer_id)
    if offer["status"] != "COUNTERED":
        fail("ERR_OFFER_NOT_NEGOTIABLE", "only a COUNTERED offer may be revised")

    festival = db.festivals[offer["festival_id"]]
    tier = db.budget_tiers[offer["budget_tier_id"]]
    stage = db.stages[offer["stage_id"]]
    artist = db.artists[offer["artist_id"]]

    candidate = dict(offer)
    candidate["guarantee_cents"] = guarantee_cents
    if production_fee_cents is not None:
        candidate["production_fee_cents"] = production_fee_cents
    if billing_position is not None:
        candidate["billing_position"] = billing_position
    if set_length_minutes is not None:
        candidate["set_length_minutes"] = set_length_minutes
    if slot_start is not None:
        candidate["slot_start_utc"] = iso_instant(slot_start)
    if offer_expires is not None:
        candidate["offer_expires_utc"] = iso_instant(offer_expires)
    new_start = stored_instant(candidate["slot_start_utc"])
    new_end = _slot_end(new_start, candidate["set_length_minutes"])
    candidate["slot_end_utc"] = iso_instant(new_end)

    _check_posture(festival)
    _check_risk(artist)
    _check_not_expired(offer)
    _check_stage_interval(stage, new_start, new_end, offer["id"])
    _check_curfew(stage, new_start, new_end)
    _check_day_load(stage, new_start, candidate["set_length_minutes"], offer["id"])
    _check_event_window(festival, new_start, new_end)
    _check_billing_position(stage, new_start, candidate["billing_position"], offer["id"])
    _check_flagship(stage, candidate["billing_position"])
    if offer["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "the negotiation round cap is reached")
    _check_genre_cap(festival, artist, candidate)
    ceiling, factor = _check_ceiling(festival, tier, artist, candidate)

    offer["guarantee_cents"] = candidate["guarantee_cents"]
    offer["production_fee_cents"] = candidate["production_fee_cents"]
    offer["billing_position"] = candidate["billing_position"]
    offer["set_length_minutes"] = candidate["set_length_minutes"]
    offer["slot_start_utc"] = candidate["slot_start_utc"]
    offer["slot_end_utc"] = candidate["slot_end_utc"]
    offer["offer_expires_utc"] = candidate["offer_expires_utc"]
    offer["status"] = "ISSUED"
    offer["round_number"] = offer["round_number"] + 1
    offer["guarantee_ceiling_cents"] = ceiling
    offer["genre_balance_factor"] = float(factor)
    offer["counter_guarantee_cents"] = None
    offer["counter_billing_position"] = None
    offer["counter_set_length_minutes"] = None
    offer["counter_note"] = None
    offer["issued_by_user_id"] = g.user_id
    touch(offer)
    return respond_object(public(offer))


# --------------------------------------------------------------------------- #
# POST /offers/{id}/accept
# --------------------------------------------------------------------------- #
@bp.post("/offers/<offer_id>/accept")
@endpoint(["ArtistRep"])
def accept_offer(offer_id):
    offer = load("offers", offer_id)
    require_artist_scope(offer["artist_id"])
    if offer["status"] != "ISSUED":
        fail("ERR_OFFER_NOT_NEGOTIABLE", "only an ISSUED offer may be accepted")

    festival = db.festivals[offer["festival_id"]]
    tier = db.budget_tiers[offer["budget_tier_id"]]
    stage = db.stages[offer["stage_id"]]
    artist = db.artists[offer["artist_id"]]
    slot_start = stored_instant(offer["slot_start_utc"])
    slot_end = stored_instant(offer["slot_end_utc"])

    _check_posture(festival)
    if offer["replaces_booking_id"] is not None:
        replaced = db.bookings.get(offer["replaces_booking_id"])
        if replaced is None or replaced["contract_status"] != "CANCELLED":
            fail(
                "ERR_REPLACEMENT_TARGET_NOT_CANCELLED",
                "the replaced booking is not cancelled",
            )
    _check_not_expired(offer)
    _check_stage_interval(stage, slot_start, slot_end, offer["id"])
    if calc.artist_double_booked(
        festival["id"], artist["id"], slot_start.date(), offer["id"]
    ):
        fail("ERR_ARTIST_DOUBLE_BOOKED", "the act is already committed on that date")
    _check_billing_position(stage, slot_start, offer["billing_position"], offer["id"])
    if tier["status"] != "OPEN":
        fail("ERR_TIER_CLOSED", "the budget tier is closed")
    if (
        tier["committed_cents"] + offer["guarantee_cents"] + offer["production_fee_cents"]
        > tier["allocation_cents"]
    ):
        fail("ERR_TIER_ALLOCATION_EXCEEDED", "the tier allocation would be overcommitted")

    booking = derive.cascade_accept(offer, festival, tier, stage)
    return respond_object(public(booking), 201)


# --------------------------------------------------------------------------- #
# POST /offers/{id}/decline
# --------------------------------------------------------------------------- #
@bp.post("/offers/<offer_id>/decline")
@endpoint(["ArtistRep"])
def decline_offer(offer_id):
    payload = body()
    opt_string(payload, "decline_reason", None, 1, None)

    offer = load("offers", offer_id)
    require_artist_scope(offer["artist_id"])
    if offer["status"] not in ("ISSUED", "COUNTERED"):
        fail("ERR_OFFER_NOT_NEGOTIABLE", "only a live offer may be declined")

    offer["status"] = "DECLINED"
    touch(offer)
    derive.release_clause(calc.clause_for_offer(offer["id"]))
    return respond_object(public(offer))


# --------------------------------------------------------------------------- #
# POST /offers/sweep-expired
# --------------------------------------------------------------------------- #
@bp.post("/offers/sweep-expired")
@endpoint(["TalentBuyer", "BusinessAffairs"])
def sweep_expired():
    payload = body()
    festival_id = opt_id(payload, "festival_id", None)

    now = db.clock
    candidates = []
    for offer in db.offers.values():
        if offer["status"] not in ("ISSUED", "COUNTERED"):
            continue
        if festival_id is not None and offer["festival_id"] != festival_id:
            continue
        if stored_instant(offer["offer_expires_utc"]) <= now:
            candidates.append(offer)

    candidates.sort(key=lambda o: o["_seq"])
    candidates.sort(key=lambda o: stored_instant(o["offer_expires_utc"]))

    released = 0
    for offer in candidates:
        offer["status"] = "EXPIRED"
        touch(offer)
        clause = calc.clause_for_offer(offer["id"])
        if clause is not None and clause["enforcement_status"] != "RELEASED":
            derive.release_clause(clause)
            released += 1

    return respond_object(
        {
            "expired_count": len(candidates),
            "expired_offer_ids": [o["id"] for o in candidates],
            "released_clause_count": released,
        }
    )
