"""The tentative hold hierarchy: ranking, challenges and deadlines (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import clock
import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, touch
from response import entity_response
from routes.common import listing, policy_window_of_booking, require_standing
from services import engine
from util import intervals_intersect, iso_instant, parse_date, parse_instant

bp = Blueprint("holds", __name__)


@bp.post("/bookings/<booking_id>/holds")
@endpoint("SalesManager")
def place_hold(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()

    # ladder step 7 then step 11: the optimistic-concurrency guard
    expected = validate.req_int(payload, "expected_booking_version")
    if expected != booking["version"]:
        raise err("ERR_STALE_BOOKING_VERSION")

    interval_start = parse_date(booking["move_in_start_date"])
    interval_end = parse_date(booking["move_out_end_date"])
    space_id = booking["space_id"]

    # ladder step 15: maintenance clearance, then the confirmed-hold conflict
    if not engine.interval_clears_all_blackouts(space_id, interval_start, interval_end):
        raise err("ERR_MAINTENANCE_BLACKOUT_CONFLICT")
    related = lookups.related_space_ids(space_id)
    for other in db.holds.rows():
        if other["status"] != "CONFIRMED":
            continue
        if engine.hold_space_id(other) not in related:
            continue
        other_start, other_end = engine.hold_interval(other)
        if intervals_intersect(interval_start, interval_end, other_start, other_end):
            raise err("ERR_SPACE_DATE_CONFLICT")

    # ladder step 16: the per-booking hold ceiling
    window = policy_window_of_booking(booking)
    if window is not None and booking["hold_count"] >= window["max_holds_per_booking"]:
        raise err("ERR_HOLD_LIMIT_REACHED")

    # ladder step 18: fiscal posture of the client
    require_standing(db.clients.get(booking["client_id"]))

    hold = db.insert(
        "hold",
        {
            "booking_id": booking["id"],
            "challenged_by_hold_id": None,
            "hold_rank": 1,
            "status": "ACTIVE",
            "challenge_round": 0,
            "challenge_deadline_utc": None,
            "release_deadline_utc": engine.release_deadline_for(
                parse_date(booking["show_start_date"])
            ),
            "interval_start_date": booking["move_in_start_date"],
            "interval_end_date": booking["move_out_end_date"],
        },
    )
    engine.assign_hold_rank_on_insert(hold)
    booking["hold_count"] = booking["hold_count"] + 1
    touch(booking)
    return entity_response(hold, 201)


@bp.get("/holds")
@endpoint("VenueAdmin", "SalesManager", "FacilitiesPlanner")
def list_holds():
    rows = filter_rows(
        "hold",
        {
            "booking_id": "booking_id",
            "challenged_by_hold_id": "challenged_by_hold_id",
            "status": "status",
        },
    )
    return listing(rows)


@bp.get("/holds/<hold_id>")
@endpoint("VenueAdmin", "SalesManager", "FacilitiesPlanner")
def read_hold(hold_id):
    return entity_response(lookups.fetch("hold", hold_id))


@bp.post("/holds/<hold_id>/challenge")
@endpoint("SalesManager")
def challenge_hold(hold_id):
    target = lookups.fetch("hold", hold_id)
    payload = body()

    # ladder step 5: the challenger reference resolves before any state is read
    challenger_id = payload.get("challenger_hold_id")
    if challenger_id is None or not isinstance(challenger_id, str) or not challenger_id.strip():
        raise err("ERR_INVALID_REQUEST", "Field 'challenger_hold_id' is required.")
    challenger = lookups.fetch("hold", challenger_id)

    # ladder step 9: both holds must be ACTIVE
    if target["status"] != "ACTIVE" or challenger["status"] != "ACTIVE":
        raise err("ERR_HOLD_STATE_INVALID")

    target_booking = db.bookings.get(target["booking_id"])
    challenger_booking = db.bookings.get(challenger["booking_id"])
    target_window = policy_window_of_booking(target_booking)
    challenger_window = policy_window_of_booking(challenger_booking)

    # ladder step 16: the challenge must be permitted, then bounded
    related = lookups.related_space_ids(target_booking["space_id"])
    t_start, t_end = engine.hold_interval(target)
    c_start, c_end = engine.hold_interval(challenger)
    overlapping = (
        challenger_booking["space_id"] in related
        and intervals_intersect(t_start, t_end, c_start, c_end)
    )
    outranks = (
        target_window is not None
        and challenger_window is not None
        and challenger_window["priority_rank"] < target_window["priority_rank"]
    )
    if not overlapping or not outranks:
        raise err("ERR_CHALLENGE_NOT_PERMITTED")
    if target["challenge_round"] >= target_window["max_challenge_rounds"]:
        raise err("ERR_CHALLENGE_LIMIT_REACHED")

    target["status"] = "CHALLENGED"
    target["challenged_by_hold_id"] = challenger["id"]
    target["challenge_round"] = target["challenge_round"] + 1
    target["challenge_deadline_utc"] = iso_instant(
        clock.now() + timedelta(hours=target_window["challenge_response_hours"])
    )
    touch(target)
    return entity_response(target)


@bp.post("/holds/<hold_id>/answer-challenge")
@endpoint("SalesManager")
def answer_challenge(hold_id):
    hold = lookups.fetch("hold", hold_id)
    if hold["status"] != "CHALLENGED":
        raise err("ERR_HOLD_STATE_INVALID")
    deadline = parse_instant(hold.get("challenge_deadline_utc"))
    if deadline is not None and clock.now() > deadline:
        raise err("ERR_CHALLENGE_DEADLINE_PASSED")

    challenger = db.holds.get(hold.get("challenged_by_hold_id") or "")
    hold["status"] = "ACTIVE"
    hold["challenged_by_hold_id"] = None
    hold["challenge_deadline_utc"] = None
    touch(hold)
    if challenger is not None and challenger["status"] in engine.LIVE_HOLD_STATES:
        engine.release_hold(challenger, booking_release_states=("TENTATIVE",))
    return entity_response(hold)


@bp.post("/holds/<hold_id>/confirm-first-option")
@endpoint("SalesManager")
def confirm_first_option(hold_id):
    hold = lookups.fetch("hold", hold_id)
    if hold["status"] != "ACTIVE":
        raise err("ERR_HOLD_STATE_INVALID")
    deadline = parse_instant(hold.get("release_deadline_utc"))
    if deadline is not None and clock.now() > deadline:
        raise err("ERR_RELEASE_DEADLINE_PASSED")
    if hold["hold_rank"] != 1:
        raise err("ERR_HOLD_NOT_FIRST_OPTION")

    hold["status"] = "CONFIRMED"
    touch(hold)
    return entity_response(hold)


@bp.post("/holds/<hold_id>/release")
@endpoint("SalesManager", "VenueAdmin")
def release_hold_route(hold_id):
    hold = lookups.fetch("hold", hold_id)
    if hold["status"] != "ACTIVE":
        raise err("ERR_HOLD_STATE_INVALID")
    engine.release_hold(hold)
    return entity_response(hold)
