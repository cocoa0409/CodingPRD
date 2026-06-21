"""SickCall and ReserveCallup routes (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import (
    not_found, forbidden, invalid_state, cross_entity_state,
    no_reserve_available, faa_duty_cap, faa_flight_cap, crew_rest_violation,
)
from middleware import require_roles, ROLE_PLANNER, ROLE_OPS, ROLE_CREW
from response import success, paginated
from routes.common import (
    get_json_body, parse_pagination, sort_by_created_at, slice_page,
)
from services.constants import SICK_REASON_CODES, MAX_CALLUP_ATTEMPTS
from services import validate
from services.calc import (
    select_reserve, faa_preview_violations, crew_rest_passes,
)
from services.entity import stamp_new, touch
from services.timeutil import parse_iso, diff_minutes_floor


sick_bp = Blueprint("sick_calls", __name__)
reserve_bp = Blueprint("reserve_callups", __name__)


# ---------------------------------------------------------------------
# SickCall
# ---------------------------------------------------------------------

SICK_REQUIRED = ("assignment_id", "reason_code")
SICK_ALLOWED = set(SICK_REQUIRED)


@sick_bp.route("/sick-calls", methods=["POST"])
def create_sick_call():
    user_id, role = require_roles({ROLE_CREW})
    body = validate.ensure_dict(get_json_body())
    validate.require_fields(body, SICK_REQUIRED)
    validate.reject_extra(body, SICK_ALLOWED)
    assignment_id = validate.check_string(body, "assignment_id")
    reason_code = validate.check_enum(body, "reason_code", SICK_REASON_CODES)

    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("assignment_id does not resolve")
    if a["crew_member_id"] != user_id:
        raise forbidden("Assignment not owned by acting crew member")

    p = db.pairings.get(a["pairing_id"])
    if p is None:
        raise not_found("Parent Pairing not found")

    # PRD §3.4: hours_before_departure = integer hours from reported_utc to
    # parent Pairing's scheduled_start_utc (negative if past departure).
    reported_dt = db.current_utc
    start = parse_iso(p["scheduled_start_utc"])
    hours_before = int(diff_minutes_floor(start, reported_dt) // 60)

    record = {
        "assignment_id": assignment_id,
        "reported_utc": db.now_iso(),
        "reason_code": reason_code,
        "state": "REPORTED",
        "hours_before_departure": hours_before,
    }
    stamp_new(record)
    db.sick_calls[record["id"]] = record
    return success(record, status=201)


@sick_bp.route("/sick-calls", methods=["GET"])
def list_sick_calls():
    require_roles({ROLE_OPS, ROLE_PLANNER})
    limit, offset = parse_pagination()
    rows = list(db.sick_calls.values())
    assignment_id = request.args.get("assignment_id")
    state = request.args.get("state")
    if assignment_id:
        rows = [r for r in rows if r["assignment_id"] == assignment_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@sick_bp.route("/sick-calls/<sick_call_id>", methods=["GET"])
def get_sick_call(sick_call_id):
    require_roles({ROLE_OPS, ROLE_PLANNER, ROLE_CREW})
    sc = db.sick_calls.get(sick_call_id)
    if sc is None:
        raise not_found("SickCall not found")
    return success(sc, status=200)


@sick_bp.route("/sick-calls/<sick_call_id>/acknowledge", methods=["POST"])
def acknowledge_sick_call(sick_call_id):
    require_roles({ROLE_OPS})
    sc = db.sick_calls.get(sick_call_id)
    if sc is None:
        raise not_found("SickCall not found")
    if sc["state"] != "REPORTED":
        raise invalid_state(f"Cannot acknowledge SickCall in state {sc['state']!r}")

    # Cross-entity: referenced Assignment must be SCHEDULED or CONFIRMED.
    a = db.assignments.get(sc["assignment_id"])
    if a is None:
        raise not_found("Assignment referenced by SickCall not found")
    if a["state"] not in {"SCHEDULED", "CONFIRMED"}:
        raise cross_entity_state(
            f"Referenced Assignment must be SCHEDULED or CONFIRMED, got {a['state']!r}"
        )

    pairing = db.pairings.get(a["pairing_id"])
    if pairing is None:
        raise not_found("Parent Pairing not found")

    # Run reserve selector first — failure must leave SickCall unchanged
    # (priority 16: ERR_NO_RESERVE_AVAILABLE).
    required_seat = a["seat"]
    selected = select_reserve(pairing, required_seat, excluded_ids=set())
    if selected is None:
        raise no_reserve_available("No eligible reserve crew available")

    # Cascades fire atomically.
    sc["state"] = "ACKNOWLEDGED"
    touch(sc)
    # Sick-calling crew → SICK.
    sick_cm = db.crew_members.get(a["crew_member_id"])
    if sick_cm is not None:
        sick_cm["status"] = "SICK"
        touch(sick_cm)
    # Mint ReserveCallup #1.
    callup = {
        "sick_call_id": sc["id"],
        "callup_sequence": 1,
        "selected_reserve_id": selected["id"],
        "state": "OFFERED",
        "offered_utc": db.now_iso(),
        "replacement_assignment_id": None,
    }
    stamp_new(callup)
    db.reserve_callups[callup["id"]] = callup
    return success(sc, status=200)


# ---------------------------------------------------------------------
# ReserveCallup
# ---------------------------------------------------------------------

@reserve_bp.route("/reserve-callups", methods=["GET"])
def list_reserve_callups():
    user_id, role = require_roles({ROLE_OPS, ROLE_CREW})
    limit, offset = parse_pagination()
    rows = list(db.reserve_callups.values())
    sick_call_id = request.args.get("sick_call_id")
    selected_reserve_id = request.args.get("selected_reserve_id")
    replacement_assignment_id = request.args.get("replacement_assignment_id")
    state = request.args.get("state")
    if sick_call_id:
        rows = [r for r in rows if r["sick_call_id"] == sick_call_id]
    if selected_reserve_id:
        rows = [r for r in rows if r["selected_reserve_id"] == selected_reserve_id]
    if replacement_assignment_id:
        rows = [r for r in rows if r.get("replacement_assignment_id") == replacement_assignment_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if role == ROLE_CREW:
        rows = [r for r in rows if r["selected_reserve_id"] == user_id]
    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@reserve_bp.route("/reserve-callups/<callup_id>", methods=["GET"])
def get_reserve_callup(callup_id):
    require_roles({ROLE_OPS, ROLE_CREW})
    rc = db.reserve_callups.get(callup_id)
    if rc is None:
        raise not_found("ReserveCallup not found")
    return success(rc, status=200)


@reserve_bp.route("/reserve-callups/<callup_id>/accept", methods=["POST"])
def accept_reserve_callup(callup_id):
    user_id, role = require_roles({ROLE_CREW})
    rc = db.reserve_callups.get(callup_id)
    if rc is None:
        raise not_found("ReserveCallup not found")
    if rc["selected_reserve_id"] != user_id:
        raise forbidden("ReserveCallup is not addressed to acting crew member")
    if rc["state"] != "OFFERED":
        raise invalid_state(f"Cannot accept ReserveCallup in state {rc['state']!r}")

    sc = db.sick_calls.get(rc["sick_call_id"])
    if sc is None:
        raise not_found("SickCall not found")
    if sc["state"] != "ACKNOWLEDGED":
        raise cross_entity_state(
            f"SickCall must be ACKNOWLEDGED, got {sc['state']!r}"
        )
    a_orig = db.assignments.get(sc["assignment_id"])
    if a_orig is None:
        raise not_found("Original Assignment not found")
    if a_orig["state"] != "CONFIRMED":
        raise cross_entity_state(
            f"Original Assignment must be CONFIRMED, got {a_orig['state']!r}"
        )
    pairing = db.pairings.get(a_orig["pairing_id"])
    if pairing is None:
        raise not_found("Pairing not found")

    # Business-safety checks on the accepting reserve.
    reserve_cm = db.crew_members[user_id]
    duty_exceeds, flight_exceeds = faa_preview_violations(reserve_cm, pairing)
    if duty_exceeds:
        raise faa_duty_cap()
    if flight_exceeds:
        raise faa_flight_cap()
    if not crew_rest_passes(reserve_cm, pairing):
        raise crew_rest_violation()

    # Cascade chain (PRD §3.4).
    # Original Assignment CONFIRMED → RECOVERED.
    a_orig["state"] = "RECOVERED"
    touch(a_orig)
    # New replacement Assignment.
    replacement = {
        "pairing_id": a_orig["pairing_id"],
        "crew_member_id": reserve_cm["id"],
        "seat": a_orig["seat"],
        "source": "RESERVE_CALLUP",
        "state": "CONFIRMED",
        "actual_duty_start_utc": None,
        "actual_duty_end_utc": None,
        "flight_minutes_credited": 0,
        "duty_minutes_credited": 0,
    }
    stamp_new(replacement)
    db.assignments[replacement["id"]] = replacement
    # ReserveCallup state and replacement_assignment_id.
    rc["state"] = "ACCEPTED"
    rc["replacement_assignment_id"] = replacement["id"]
    touch(rc)
    # SickCall → CLOSED.
    sc["state"] = "CLOSED"
    touch(sc)
    return success(rc, status=200)


@reserve_bp.route("/reserve-callups/<callup_id>/decline", methods=["POST"])
def decline_reserve_callup(callup_id):
    user_id, role = require_roles({ROLE_CREW})
    rc = db.reserve_callups.get(callup_id)
    if rc is None:
        raise not_found("ReserveCallup not found")
    if rc["selected_reserve_id"] != user_id:
        raise forbidden("ReserveCallup is not addressed to acting crew member")
    if rc["state"] != "OFFERED":
        raise invalid_state(f"Cannot decline ReserveCallup in state {rc['state']!r}")

    sick_call_id = rc["sick_call_id"]
    sc = db.sick_calls.get(sick_call_id)
    if sc is None:
        raise not_found("SickCall not found")

    # Build excluded set: all crew already offered for this SickCall (any state).
    excluded = {c["selected_reserve_id"]
                for c in db.reserve_callups.values()
                if c["sick_call_id"] == sick_call_id}

    # Find max callup_sequence so far for this sick_call.
    seqs = [c["callup_sequence"] for c in db.reserve_callups.values()
            if c["sick_call_id"] == sick_call_id]
    next_seq = max(seqs) + 1 if seqs else 1

    if next_seq > MAX_CALLUP_ATTEMPTS:
        raise no_reserve_available("Maximum callup attempts exceeded")

    a_orig = db.assignments.get(sc["assignment_id"])
    if a_orig is None:
        raise not_found("Assignment not found")
    pairing = db.pairings.get(a_orig["pairing_id"])
    if pairing is None:
        raise not_found("Pairing not found")
    required_seat = a_orig["seat"]
    next_reserve = select_reserve(pairing, required_seat, excluded_ids=excluded)
    if next_reserve is None:
        raise no_reserve_available("No eligible reserve crew available")

    # Decline current and mint next.
    rc["state"] = "DECLINED"
    touch(rc)
    new_callup = {
        "sick_call_id": sick_call_id,
        "callup_sequence": next_seq,
        "selected_reserve_id": next_reserve["id"],
        "state": "OFFERED",
        "offered_utc": db.now_iso(),
        "replacement_assignment_id": None,
    }
    stamp_new(new_callup)
    db.reserve_callups[new_callup["id"]] = new_callup
    return success(rc, status=200)
