"""Engagement negotiation, sign-off, close and withdrawal (PRD 3.2, 3.9)."""
from datetime import timedelta

from flask import Blueprint

import serialize
from auth import ROLE_BOX, ROLE_EXEC, ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, authorize
from calc import MAX_NEGOTIATION_ROUNDS, OFFER_VALIDITY_HOURS, booking_min_run_compliance
from cascade import Ledger, cancel_showtime
from errors import ApiError
from response import object_response, paged
from store import new_record, now, ordered, touch
from validate import (TERMS_VARIANTS, bad, body, find, insert, must_find, opt_id,
                      query_str, req_day, req_enum, req_id, req_int, req_share,
                      req_str, rows)

bp = Blueprint("bookings", __name__)

STAFF_READ = (ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, ROLE_BOX, ROLE_EXEC)
NEGOTIABLE = ("OFFERED", "COUNTERED")


def booking_rounds(booking_id):
    return sorted([o for o in rows("offers") if o["booking_id"] == booking_id],
                  key=lambda o: o["round_index"])


def pending_round(booking_id):
    for offer in booking_rounds(booking_id):
        if offer["outcome"] == "PENDING":
            return offer
    return None


def require_pending_round(booking_id):
    offer = pending_round(booking_id)
    if offer is None:
        raise ApiError("ERR_BOOKING_OFFER_NOT_FOUND",
                       "This engagement has no pending negotiation round.")
    return offer


def require_state(booking, allowed):
    if booking["status"] not in allowed:
        raise ApiError("ERR_BOOKING_INVALID_STATE",
                       "An engagement in %s does not admit this transition." % booking["status"])


def check_occ_booking(booking, payload):
    expected = req_int(payload, "expected_booking_version", minimum=0)
    if expected != booking["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION",
                       "expected_booking_version %d does not match %d."
                       % (expected, booking["version"]))


def check_guarantee(distributor, guarantee_cents):
    if distributor["requires_advance_guarantee"] and guarantee_cents <= 0:
        raise ApiError("ERR_GUARANTEE_REQUIRED",
                       "This distributor requires a non-zero advance guarantee.")


def mint_round(booking, proposed_by, house_nut, share_pct, min_run_days, guarantee, uid):
    row = new_record(
        booking_id=booking["id"],
        round_index=booking["round_count"] + 1,
        proposed_by=proposed_by,
        proposed_house_nut_cents=house_nut,
        proposed_distributor_share_pct=share_pct,
        proposed_min_run_days=min_run_days,
        proposed_guarantee_cents=guarantee,
        outcome="PENDING",
        submitted_by_user_id=uid,
    )
    row["expires_at"] = row["created_at"] + timedelta(hours=OFFER_VALIDITY_HOURS)
    insert("offers", row)
    return row


@bp.post("/bookings")
def create_booking():
    role, uid = authorize((ROLE_PROGRAMMER,))
    payload = body()
    terms_variant = req_enum(payload, "terms_variant", TERMS_VARIANTS)
    house_nut = req_int(payload, "house_nut_cents", minimum=0)
    share_pct = req_share(payload, "distributor_share_pct")
    guarantee = req_int(payload, "guarantee_cents", minimum=0)
    min_run_days = req_int(payload, "min_run_days", minimum=1)
    start_date = req_day(payload, "engagement_start_date")
    end_date = req_day(payload, "engagement_end_date")
    if end_date < start_date:
        raise bad("engagement_end_date must not be earlier than engagement_start_date.")
    title_id = req_id(payload, "title_id")
    distributor_id = req_id(payload, "distributor_id")
    venue_id = req_id(payload, "venue_id")
    supersedes_id = opt_id(payload, "supersedes_booking_id")
    must_find("titles", title_id)
    distributor = must_find("distributors", distributor_id)
    must_find("venues", venue_id)
    superseded = None
    if supersedes_id is not None:
        superseded = must_find("bookings", supersedes_id)
        if superseded["status"] != "WITHDRAWN":
            raise ApiError("ERR_REFERENCE_MISMATCH",
                           "A superseded engagement must itself be WITHDRAWN.")
    check_guarantee(distributor, guarantee)
    row = new_record(
        title_id=title_id,
        distributor_id=distributor_id,
        venue_id=venue_id,
        supersedes_booking_id=supersedes_id,
        terms_variant=terms_variant,
        house_nut_cents=house_nut,
        distributor_share_pct=share_pct,
        guarantee_cents=guarantee,
        min_run_days=min_run_days,
        engagement_start_date=start_date,
        engagement_end_date=end_date,
        status="OFFERED",
        round_count=0,
        scheduled_showtime_count=0,
        actual_playing_days=0,
        min_run_compliant=False,
        min_run_penalty_cents=0,
        cancel_reason=None,
        created_by_user_id=uid,
        confirmed_by_user_id=None,
    )
    insert("bookings", row)
    mint_round(row, "CINEMA", house_nut, share_pct, min_run_days, guarantee, uid)
    row["round_count"] = 1
    return object_response(serialize.booking(row), 201)


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    authorize(STAFF_READ)
    return object_response(serialize.booking(must_find("bookings", booking_id)))


@bp.get("/bookings")
def list_bookings():
    authorize(STAFF_READ)
    found = rows("bookings")
    for name in ("title_id", "distributor_id", "venue_id", "supersedes_booking_id", "status"):
        value = query_str(name)
        if value is not None:
            found = [b for b in found if b[name] == value]
    return paged(ordered(found), serialize.booking)


@bp.get("/bookings/<booking_id>/offers")
def list_offers(booking_id):
    authorize((ROLE_PROGRAMMER, ROLE_EXEC))
    must_find("bookings", booking_id)
    return paged(booking_rounds(booking_id), serialize.offer)


def _lodge_round(booking_id, proposed_by, with_occ, from_states, to_state):
    role, uid = authorize((ROLE_PROGRAMMER,))
    payload = body()
    house_nut = req_int(payload, "proposed_house_nut_cents", minimum=0)
    share_pct = req_share(payload, "proposed_distributor_share_pct")
    min_run_days = req_int(payload, "proposed_min_run_days", minimum=1)
    guarantee = req_int(payload, "proposed_guarantee_cents", minimum=0)
    booking = must_find("bookings", booking_id)
    if with_occ:
        check_occ_booking(booking, payload)
    require_state(booking, from_states)
    superseded = require_pending_round(booking["id"])
    if booking["round_count"] >= MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "This engagement has used its four negotiation rounds.")
    distributor = find("distributors", booking["distributor_id"])
    if distributor is not None:
        check_guarantee(distributor, guarantee)
    superseded["outcome"] = "COUNTERED"
    touch(superseded)
    row = mint_round(booking, proposed_by, house_nut, share_pct, min_run_days,
                     guarantee, uid)
    booking["round_count"] = booking["round_count"] + 1
    booking["status"] = to_state
    touch(booking)
    return object_response(serialize.offer(row), 201)


@bp.post("/bookings/<booking_id>/counter")
def counter_booking(booking_id):
    return _lodge_round(booking_id, "DISTRIBUTOR", True, NEGOTIABLE, "COUNTERED")


@bp.post("/bookings/<booking_id>/offer")
def offer_booking(booking_id):
    return _lodge_round(booking_id, "CINEMA", False, ("COUNTERED",), "OFFERED")


@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    role, uid = authorize((ROLE_EXEC,))
    body()
    booking = must_find("bookings", booking_id)
    require_state(booking, NEGOTIABLE)
    offer = require_pending_round(booking["id"])
    if now() > offer["expires_at"]:
        offer["outcome"] = "EXPIRED"
        touch(offer)
        raise ApiError("ERR_OFFER_EXPIRED", "The pending offer has expired.")
    venue = find("venues", booking["venue_id"])
    if venue is not None and offer["proposed_house_nut_cents"] > venue["base_house_nut_weekly_cents"]:
        raise ApiError("ERR_HOUSE_NUT_ABOVE_CAP",
                       "The proposed house nut exceeds the board-approved weekly cap.")
    offer["outcome"] = "ACCEPTED"
    touch(offer)
    booking["house_nut_cents"] = offer["proposed_house_nut_cents"]
    booking["distributor_share_pct"] = offer["proposed_distributor_share_pct"]
    booking["min_run_days"] = offer["proposed_min_run_days"]
    booking["guarantee_cents"] = offer["proposed_guarantee_cents"]
    booking["confirmed_by_user_id"] = uid
    booking["status"] = "CONFIRMED"
    touch(booking)
    return object_response(serialize.booking(booking))


@bp.post("/bookings/<booking_id>/close")
def close_booking(booking_id):
    authorize((ROLE_EXEC,))
    body()
    booking = must_find("bookings", booking_id)
    require_state(booking, ("CONFIRMED", "RUNNING"))
    venue = must_find("venues", booking["venue_id"])
    figures = booking_min_run_compliance(booking, venue)
    booking["actual_playing_days"] = figures["actual_playing_days"]
    booking["min_run_penalty_cents"] = figures["min_run_penalty_cents"]
    booking["min_run_compliant"] = figures["min_run_compliant"]
    booking["status"] = "CLOSED"
    touch(booking)
    return object_response(serialize.booking(booking))


@bp.post("/bookings/<booking_id>/withdraw")
def withdraw_booking(booking_id):
    authorize((ROLE_EXEC,))
    payload = body()
    cancel_reason = req_str(payload, "cancel_reason")
    booking = must_find("bookings", booking_id)
    require_state(booking, ("OFFERED", "COUNTERED", "CONFIRMED", "RUNNING"))
    ledger = Ledger()
    # Hop one: pending rounds are rejected and the engagement is withdrawn.
    for offer in booking_rounds(booking["id"]):
        if offer["outcome"] == "PENDING":
            offer["outcome"] = "REJECTED"
            ledger.mark(offer)
    booking["status"] = "WITHDRAWN"
    booking["cancel_reason"] = cancel_reason
    ledger.mark(booking)
    # Hop two: live clearances on the engagement are revoked.
    revoked = []
    for clearance in rows("clearances"):
        if clearance["booking_id"] != booking["id"]:
            continue
        if clearance["status"] in ("SUBMITTED", "CHANGES_REQUESTED", "CLEARED"):
            clearance["status"] = "REVOKED"
            clearance["revoked_reason"] = "BOOKING_WITHDRAWN"
            ledger.mark(clearance)
            revoked.append(clearance)
    # Hops three and four: screenings on those licences collapse with their sales.
    revoked_ids = {c["id"] for c in revoked}
    for showtime in ordered(rows("showtimes")):
        if showtime["clearance_id"] in revoked_ids and showtime["status"] == "SCHEDULED":
            cancel_showtime(showtime, "CLEARANCE_REVOKED", ledger)
    ledger.flush()
    return object_response(serialize.booking(booking))
