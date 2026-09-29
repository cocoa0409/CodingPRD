"""Showing appointments: booking and the showing state machine (PRD §3.6)."""
from flask import Blueprint

import calc
import serialize
from core import (
    ADMIN, MEMBER, READ_ROLES, authenticate, body, db, fail, lookup,
    new_common, now, ok, ordered, paginate, parse_dt, present, qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_owner, assert_transition, assert_version,
    require_action, require_version_field,
)

bp = Blueprint("showing", __name__)

SHOWING_TRANSITIONS = {
    "CONFIRM": ("REQUESTED",),
    "CANCEL": ("REQUESTED", "CONFIRMED"),
    "COMPLETE": ("CONFIRMED",),
    "MARK_NO_SHOW": ("CONFIRMED",),
}


@bp.post("/showing-appointments")
def request_showing():
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    listing = None
    member = None
    if present(payload, "listing_id"):
        listing = lookup("listings", payload["listing_id"])
    if present(payload, "showing_member_id"):
        member = lookup("members", payload["showing_member_id"])

    # Rung 5 — request shape.
    if listing is None:
        fail("ERR_INVALID_REQUEST", "listing_id is required.")
    if member is None:
        fail("ERR_INVALID_REQUEST", "showing_member_id is required.")
    if not present(payload, "window_start") or not present(payload, "window_end"):
        fail("ERR_INVALID_REQUEST", "window_start and window_end are required.")
    window_start = parse_dt(payload["window_start"])
    window_end = parse_dt(payload["window_end"])
    if window_start is None or window_end is None:
        fail("ERR_INVALID_REQUEST", "window_start and window_end must be ISO 8601 instants.")

    # Rung 6 — Member ownership.
    assert_owner(role, user_id, member["id"])

    # Rung 14 — window geometry.
    if not (window_start < window_end):
        fail("ERR_INVALID_WINDOW", "window_start must be earlier than window_end.")

    rec = new_common()
    rec.update({
        "listing_id": listing["id"],
        "showing_member_id": member["id"],
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "status": "REQUESTED",
        "cancel_reason": None,
    })
    db.appointments[rec["id"]] = rec
    return ok(serialize.appointment(rec), 201)


@bp.get("/showing-appointments/<appointment_id>")
def read_showing(appointment_id):
    authenticate(READ_ROLES)
    return ok(serialize.appointment(lookup("appointments", appointment_id)))


@bp.get("/showing-appointments")
def list_showings():
    authenticate(READ_ROLES)
    rows = ordered(db.appointments)
    rows = qfilter(rows, "listing_id")
    rows = qfilter(rows, "showing_member_id")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.appointment)


@bp.post("/showing-appointments/<appointment_id>/state")
def showing_state(appointment_id):
    user_id, role = authenticate([ADMIN, MEMBER])
    appointment = lookup("appointments", appointment_id)
    payload = body()

    action = require_action(payload, tuple(SHOWING_TRANSITIONS))
    expected = require_version_field(payload, "expected_appointment_version")

    assert_owner(role, user_id, appointment["showing_member_id"])
    assert_version(expected, appointment)
    assert_not_terminal("appointment", appointment["status"])
    assert_transition(appointment["status"], SHOWING_TRANSITIONS, action)

    listing = db.listings.get(appointment["listing_id"])
    event_count = serialize.appointment_event_count(appointment_id)

    if action == "CONFIRM":
        if listing is None or listing["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
            fail("ERR_INVALID_STATE", "The listing is not open for showings.")
        # Rung 14 — closed-interval capacity.
        limit = listing["concurrent_showing_limit"]
        overlaps = 0
        for other in ordered(db.appointments):
            if other["id"] == appointment_id:
                continue
            if other["listing_id"] != appointment["listing_id"] or other["status"] != "CONFIRMED":
                continue
            if calc.showings_overlap(appointment, other):
                overlaps += 1
        if overlaps >= limit:
            fail("ERR_SHOWING_CAPACITY_EXCEEDED", "The listing's concurrent showing limit is reached.")
        # Rung 16 — linkage integrity.
        has_box = any(
            p["listing_id"] == appointment["listing_id"] and p["placement_status"] == "PLACED"
            for p in db.placements.values()
        )
        if not has_box:
            fail("ERR_SHOWING_NO_LOCKBOX", "The listing has no lockbox on the door.")
        appointment["status"] = "CONFIRMED"

    elif action == "CANCEL":
        appointment["status"] = "CANCELLED"
        appointment["cancel_reason"] = "AGENT_CANCELLED"

    elif action == "COMPLETE":
        if event_count < 1:
            fail("ERR_INVALID_STATE", "The showing has no attributed access events.")
        appointment["status"] = "COMPLETED"

    elif action == "MARK_NO_SHOW":
        window_end = parse_dt(appointment["window_end"])
        if window_end is None or window_end > now():
            fail("ERR_INVALID_STATE", "The showing window has not yet elapsed.")
        if event_count != 0:
            fail("ERR_INVALID_STATE", "The showing has attributed access events.")
        appointment["status"] = "NO_SHOW"

    touch(appointment)
    return ok(serialize.appointment(appointment))
