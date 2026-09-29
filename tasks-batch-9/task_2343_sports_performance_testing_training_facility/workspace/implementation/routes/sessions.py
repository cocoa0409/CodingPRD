"""Group session scheduling, staffing, execution and billing (PRD 3.5 / 3.8)."""

from datetime import timedelta

from flask import Blueprint

import response
import serializers
from db import create, now, ordered, store, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum,
                        query_instant, query_str, resolve_acting_staff,
                        slice_page, v_enum, v_instant, v_int, v_string)
from routes.common import (get_group_session, get_staff_member,
                           get_team_contract, require_state)
from services import calc, domain

bp = Blueprint("sessions", __name__)

SITE_CODES = ("ONSITE", "OFFSITE")
PHASE_FOCUS = ("GENERAL_PREP", "SPECIFIC_PREP", "COMPETITION", "TRANSITION")
SESSION_STATUSES = ("SCHEDULED", "ROSTER_LOCKED", "IN_PROGRESS", "COMPLETED", "CANCELED")
STAFFING_STATUSES = ("STAFF_PENDING", "STAFFED", "UNDERSTAFFED")
COACH_ROLES = ("LEAD", "ASSISTANT")
SESSION_TERMINAL = ("CANCELED",)


# ----------------------------------------------------------------- create ----
def _onsite_concurrency_breached(new_start, new_end):
    overlapping = [
        s
        for s in store.group_sessions.values()
        if s["site_code"] == "ONSITE"
        and s["session_status"] != "CANCELED"
        and s["_start_at"] < new_end
        and new_start < s["_end_at"]
    ]
    points = [new_start] + [s["_start_at"] for s in overlapping if s["_start_at"] > new_start]
    for point in points:
        concurrent = 1 + sum(
            1 for s in overlapping if s["_start_at"] <= point < s["_end_at"]
        )
        if concurrent > calc.FACILITY_MAX_CONCURRENT_ONSITE:
            return True
    return False


@bp.post("/group-sessions")
def create_group_session():
    guard("PerformanceDirector", "FrontDesk")
    body = body_json()

    contract = None
    if body.get("team_contract_id") is not None:
        contract = get_team_contract(body.get("team_contract_id"))

    start_at = v_instant(body, "start_at")
    end_at = v_instant(body, "end_at")
    site_code = v_enum(body, "site_code", SITE_CODES)
    station_count = v_int(body, "station_count", minimum=1, maximum=12)
    phase_focus = v_enum(body, "phase_focus", PHASE_FOCUS)
    max_athletes = v_int(body, "max_athletes", minimum=1, maximum=40)
    offsite_location = body.get("offsite_location")

    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    if site_code == "OFFSITE":
        if not isinstance(offsite_location, str) or offsite_location.strip() == "":
            raise ApiError(
                "ERR_INVALID_REQUEST", "offsite_location is required when site_code is OFFSITE"
            )
    else:
        if offsite_location is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "offsite_location must be null when site_code is ONSITE"
            )

    if site_code == "ONSITE" and _onsite_concurrency_breached(start_at, end_at):
        raise ApiError(
            "ERR_SITE_CONCURRENCY_EXCEEDED",
            "At most three onsite sessions may overlap at any instant",
        )

    if contract is not None and contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "The referenced team contract is not ACTIVE")

    record = create(
        store.group_sessions,
        {
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "_start_at": start_at,
            "_end_at": end_at,
            "site_code": site_code,
            "offsite_location": offsite_location,
            "station_count": station_count,
            "phase_focus": phase_focus,
            "max_athletes": max_athletes,
            "team_contract_id": contract["id"] if contract else None,
            "assigned_staff": [],
            "session_status": "SCHEDULED",
            "billed_rate_cents": None,
            "rate_tier_applied": None,
            "delivered_slots_at_completion": None,
            "cancel_reason": None,
        },
    )
    return response.created(serializers.group_session(record))


@bp.get("/group-sessions/<group_session_id>")
def read_group_session(group_session_id):
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk", "Athlete", "Guardian")
    session = get_group_session(group_session_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.group_session(session))


@bp.get("/group-sessions")
def list_group_sessions():
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    site_code = query_enum("site_code", SITE_CODES)
    session_status = query_enum("session_status", SESSION_STATUSES)
    staffing_status = query_enum("staffing_status", STAFFING_STATUSES)
    team_contract_id = query_str("team_contract_id")
    from_at = query_instant("from_at")
    to_at = query_instant("to_at")

    rows = ordered(store.group_sessions)
    if site_code:
        rows = [r for r in rows if r["site_code"] == site_code]
    if session_status:
        rows = [r for r in rows if r["session_status"] == session_status]
    if staffing_status:
        rows = [
            r for r in rows if domain.session_derived(r)["staffing_status"] == staffing_status
        ]
    if team_contract_id:
        rows = [r for r in rows if r["team_contract_id"] == team_contract_id]
    if from_at is not None:
        rows = [r for r in rows if r["_end_at"] > from_at]
    if to_at is not None:
        rows = [r for r in rows if r["_start_at"] < to_at]

    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.group_session(r) for r in page], limit, offset, total)


# ---------------------------------------------------------- coach assignment ----
def _different_location(a, b):
    if a["site_code"] != b["site_code"]:
        return True
    if a["site_code"] == "OFFSITE" and a["offsite_location"] != b["offsite_location"]:
        return True
    return False


def _closed_overlap(a, b):
    return not (a["_start_at"] > b["_end_at"] or b["_start_at"] > a["_end_at"])


@bp.post("/group-sessions/<group_session_id>/coaches")
def assign_coach(group_session_id):
    guard("PerformanceDirector", "FrontDesk")
    session = get_group_session(group_session_id)
    body = body_json()
    staff = get_staff_member(body.get("staff_member_id"))

    expected = v_int(body, "expected_group_session_version")
    coach_role = v_enum(
        body,
        "coach_role",
        COACH_ROLES,
        required=False,
        default="LEAD" if not session["assigned_staff"] else "ASSISTANT",
    )

    if expected != session["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_group_session_version does not match the session's current version",
        )

    require_state(session, "session_status", ("SCHEDULED",), SESSION_TERMINAL, "GroupSession")
    domain.credential_gate(staff)

    for other in domain.sessions_for_staff(staff["id"]):
        if other["id"] == session["id"]:
            continue
        if other["session_status"] == "CANCELED":
            continue
        if _closed_overlap(other, session):
            touching = (
                other["_end_at"] == session["_start_at"]
                or session["_end_at"] == other["_start_at"]
            )
            if touching and not _different_location(other, session):
                continue
            raise ApiError(
                "ERR_STAFF_SCHEDULE_CONFLICT",
                "The staff member already holds an overlapping assignment",
            )

    buffer_delta = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)
    for other in domain.sessions_for_staff(staff["id"]):
        if other["id"] == session["id"]:
            continue
        if other["session_status"] == "CANCELED":
            continue
        if not _different_location(other, session):
            continue
        if other["_end_at"] <= session["_start_at"]:
            gap = session["_start_at"] - other["_end_at"]
        elif session["_end_at"] <= other["_start_at"]:
            gap = other["_start_at"] - session["_end_at"]
        else:
            continue
        if gap < buffer_delta:
            raise ApiError(
                "ERR_TRAVEL_BUFFER_VIOLATION",
                "At least 30 minutes are required between assignments at different locations",
            )

    session["assigned_staff"] = list(session["assigned_staff"]) + [
        {"staff_member_id": staff["id"], "coach_role": coach_role}
    ]
    touch(session)
    domain.apply_staffing_side_effects(session)
    return response.ok(serializers.group_session(session))


# ------------------------------------------------------------- lifecycle ----
@bp.post("/group-sessions/<group_session_id>/lock-roster")
def lock_roster(group_session_id):
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk")
    session = get_group_session(group_session_id)
    resolve_acting_staff(ctx)
    body_json()

    require_state(session, "session_status", ("SCHEDULED",), SESSION_TERMINAL, "GroupSession")
    derived = domain.session_derived(session)
    if derived["staffing_status"] != "STAFFED":
        raise ApiError(
            "ERR_COACH_RATIO_EXCEEDED",
            "The roster cannot be locked while the session is not fully staffed",
        )
    if not session["_start_at"] > now():
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW_CLOSED",
            "The roster cannot be locked once start_at has been reached",
        )
    if derived["reserved_count"] < 1:
        raise ApiError("ERR_INVALID_STATE", "The session holds no reserved enrollment to lock")

    session["session_status"] = "ROSTER_LOCKED"
    touch(session)
    domain.assign_stations(session)
    return response.ok(serializers.group_session(session))


@bp.post("/group-sessions/<group_session_id>/start")
def start_session(group_session_id):
    ctx = guard("Coach")
    session = get_group_session(group_session_id)
    resolve_acting_staff(ctx)
    body_json()

    require_state(session, "session_status", ("ROSTER_LOCKED",), SESSION_TERMINAL, "GroupSession")
    if domain.session_derived(session)["staffing_status"] != "STAFFED":
        raise ApiError(
            "ERR_COACH_RATIO_EXCEEDED", "The session is no longer fully staffed and cannot start"
        )
    if now() < session["_start_at"]:
        raise ApiError("ERR_INVALID_STATE", "The session's start_at has not been reached yet")

    session["session_status"] = "IN_PROGRESS"
    touch(session)
    return response.ok(serializers.group_session(session))


def _bill_contract(session):
    contract = store.team_contracts.get(session["team_contract_id"])
    if contract is None:
        return
    delivered_before = contract["sessions_delivered"]
    tier = calc.rate_tier_for(delivered_before)
    rate = calc.billed_rate_cents(contract["base_rate_cents"], tier, session["site_code"])
    slots = sum(
        1
        for e in domain.session_enrollments(session["id"])
        if e.get("funding_source") == "TEAM_CONTRACT" and e["status"] in ("ATTENDED", "NO_SHOW")
    )
    session["rate_tier_applied"] = tier
    session["billed_rate_cents"] = rate
    session["delivered_slots_at_completion"] = slots

    contract["sessions_reserved"] -= slots
    contract["sessions_delivered"] = delivered_before + slots
    contract["billed_amount_cents"] += rate * slots
    if contract["status"] == "ACTIVE" and contract["sessions_delivered"] == contract["contracted_sessions"]:
        contract["status"] = "CLOSED"
    touch(contract)


@bp.post("/group-sessions/<group_session_id>/complete")
def complete_session(group_session_id):
    ctx = guard("Coach")
    session = get_group_session(group_session_id)
    resolve_acting_staff(ctx)
    body_json()

    require_state(session, "session_status", ("IN_PROGRESS",), SESSION_TERMINAL, "GroupSession")

    for enrollment in domain.session_enrollments(session["id"]):
        if enrollment["status"] == "RESERVED":
            domain.mark_no_show(enrollment, session)
    for enrollment in domain.session_enrollments(session["id"]):
        if enrollment["status"] == "WAITLISTED":
            enrollment["status"] = "CANCELED"
            enrollment["cancel_reason"] = "SESSION_CANCELED"
            touch(enrollment)

    session["session_status"] = "COMPLETED"
    touch(session)
    if session["team_contract_id"]:
        _bill_contract(session)
    return response.ok(serializers.group_session(session))


@bp.post("/group-sessions/<group_session_id>/void-completion")
def void_completion(group_session_id):
    guard("PerformanceDirector")
    session = get_group_session(group_session_id)
    body = body_json()
    v_string(body, "void_reason", required=False, max_len=500)

    require_state(session, "session_status", ("COMPLETED",), SESSION_TERMINAL, "GroupSession")
    enrollments = domain.session_enrollments(session["id"])
    if any(e["status"] == "NO_SHOW" for e in enrollments):
        raise ApiError(
            "ERR_VOID_BLOCKED_BY_NO_SHOW",
            "A completion carrying a no-show cannot be reversed",
        )

    for enrollment in enrollments:
        if enrollment["status"] != "ATTENDED":
            continue
        enrollment["status"] = "RESERVED"
        touch(enrollment)
        athlete = store.athletes.get(enrollment["athlete_id"])
        if athlete is not None:
            athlete["attended_count"] -= 1
            touch(athlete)
        domain.unconsume_package_credit(enrollment)

    contract = store.team_contracts.get(session["team_contract_id"])
    if contract is not None:
        slots = session["delivered_slots_at_completion"] or 0
        rate = session["billed_rate_cents"] or 0
        contract["sessions_delivered"] -= slots
        contract["sessions_reserved"] += slots
        contract["billed_amount_cents"] -= rate * slots
        if contract["status"] == "CLOSED" and contract["sessions_delivered"] < contract["contracted_sessions"]:
            contract["status"] = "ACTIVE"
        touch(contract)

    session["billed_rate_cents"] = None
    session["rate_tier_applied"] = None
    session["delivered_slots_at_completion"] = None
    session["session_status"] = "IN_PROGRESS"
    touch(session)
    return response.ok(serializers.group_session(session))


@bp.post("/group-sessions/<group_session_id>/cancel")
def cancel_session(group_session_id):
    guard("PerformanceDirector", "FrontDesk")
    session = get_group_session(group_session_id)
    body = body_json()
    reason = v_string(body, "cancel_reason", required=False, max_len=500)

    require_state(
        session,
        "session_status",
        ("SCHEDULED", "ROSTER_LOCKED"),
        SESSION_TERMINAL,
        "GroupSession",
    )

    for enrollment in domain.session_enrollments(session["id"]):
        if enrollment["status"] not in ("RESERVED", "WAITLISTED"):
            continue
        if enrollment["status"] == "RESERVED":
            domain.refund_funding(enrollment, session)
        enrollment["status"] = "CANCELED"
        enrollment["cancel_reason"] = "SESSION_CANCELED"
        enrollment["station_number"] = None
        touch(enrollment)

    session["session_status"] = "CANCELED"
    session["cancel_reason"] = reason
    touch(session)
    return response.ok(serializers.group_session(session))
