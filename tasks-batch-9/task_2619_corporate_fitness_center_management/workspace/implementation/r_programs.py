"""ProgramOffering and ProgramSession endpoints (PRD 3.4 / 3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascades
from core import (ApiError, ROLE_FITNESS_STAFF, ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER,
                 bad_request, body, created, find, get_or_404, new_record, now, ok, opt_enum,
                 opt_int, opt_str, req_enum, req_instant, req_int, req_str, req_str_list,
                 require, to_date, upd, view, where)
from guards import SESSION_TERMINAL, invalid_transition, require_contract_active, terminal

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = ("GROUP_EXERCISE", "PERSONAL_TRAINING", "WELLNESS_CHALLENGE")
MEMBER_CLASSES = ("EMPLOYEE", "DEPENDENT", "RETIREE")
CREDENTIAL_TYPES = ("CPR_AED", "FIRST_AID", "GROUP_EX_CERT", "PT_CERT")
ROOM_BUFFER_MINUTES = 15
START_GRACE_MINUTES = 15


# --------------------------------------------------------------------------
# Offerings
# --------------------------------------------------------------------------
@bp.post("/program-offerings")
def create_offering():
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    data = body()
    contract_id = req_str(data, "contract_id")
    lead_staff_id = req_str(data, "lead_staff_id")
    program_type = req_enum(data, "program_type", PROGRAM_TYPES)
    title = req_str(data, "title", 1, 200)
    participation_target = req_int(data, "participation_target", minimum=1)
    max_participants_per_session = req_int(data, "max_participants_per_session", minimum=1)
    required_credential_type = req_enum(data, "required_credential_type", CREDENTIAL_TYPES)
    eligible_member_classes = req_str_list(data, "eligible_member_classes", MEMBER_CLASSES,
                                          default=["EMPLOYEE"])
    get_or_404("contract", contract_id)
    lead = get_or_404("staff", lead_staff_id)
    if lead["duty_status"] != "ACTIVE_DUTY":
        raise ApiError("ERR_STAFF_NOT_ON_DUTY", 422)
    if lead["contract_id"] != contract_id:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    offering = new_record("offering", {
        "contract_id": contract_id,
        "lead_staff_id": lead_staff_id,
        "program_type": program_type,
        "title": title,
        "participation_target": participation_target,
        "max_participants_per_session": max_participants_per_session,
        "eligible_member_classes": eligible_member_classes,
        "required_credential_type": required_credential_type,
        "status": "DRAFT",
        "provisional_attainment_pct": 0,
        "final_attainment_pct": 0,
        "counted_participation_total": 0,
        "coverage_gap_count": 0,
    })
    return created(view(offering))


@bp.post("/program-offerings/<oid>/status-changes")
def offering_status_change(oid):
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    offering = get_or_404("offering", oid)
    data = body()
    action = req_enum(data, "action", ("ACTIVATE", "PAUSE", "RESUME", "CLOSE"))
    opt_str(data, "reason", 1, 500)
    terminal(offering["status"] == "CLOSED")
    contract = find("contract", offering["contract_id"])
    status = offering["status"]
    if action == "ACTIVATE":
        if status != "DRAFT":
            invalid_transition()
        require_contract_active(contract)
        lead = find("staff", offering["lead_staff_id"])
        if lead is None or not calc.holds_live_credential(
                lead["id"], offering["required_credential_type"]):
            raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED", 422)
        if not calc.contract_has_ready_aed(offering["contract_id"]):
            raise ApiError("ERR_AED_NOT_READY", 422)
        if lead["duty_status"] != "ACTIVE_DUTY":
            raise ApiError("ERR_STAFF_NOT_ON_DUTY", 422)
        if (lead.get("readiness_index") or 0) < calc.READINESS_THRESHOLD:
            raise ApiError("ERR_READINESS_BELOW_THRESHOLD", 422)
        upd(offering, status="ACTIVE")
        cascades.refresh_attainment(offering)
    elif action == "PAUSE":
        if status != "ACTIVE":
            raise ApiError("ERR_OFFERING_NOT_ACTIVE", 409)
        cascades.pause_offering(offering)
    elif action == "RESUME":
        if status != "PAUSED":
            raise ApiError("ERR_OFFERING_NOT_ACTIVE", 409)
        require_contract_active(contract)
        upd(offering, status="ACTIVE")
    else:
        if status not in ("ACTIVE", "PAUSED"):
            invalid_transition()
        for session in where("session", offering_id=offering["id"]):
            if session["status"] in calc.OPEN_SESSION_STATUSES or \
                    session["status"] == "IN_PROGRESS":
                raise ApiError("ERR_OPEN_SESSIONS", 409)
        upd(offering, status="CLOSED")
        cascades.refresh_attainment(offering, provisional=False, final=True)
    return ok(view(offering))


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def _room_conflict(room_id, start, end, exclude_id=None):
    buffer = timedelta(minutes=ROOM_BUFFER_MINUTES)
    for session in where("session", room_id=room_id):
        if session["id"] == exclude_id:
            continue
        if session["status"] in calc.CANCELLED_SESSION_STATUSES:
            continue
        if start < session["scheduled_end_utc"] + buffer and \
                session["scheduled_start_utc"] < end + buffer:
            return True
    return False


@bp.post("/program-sessions")
def create_session():
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    data = body()
    offering_id = req_str(data, "offering_id")
    room_id = req_str(data, "room_id")
    scheduled_start_utc = req_instant(data, "scheduled_start_utc")
    scheduled_end_utc = req_instant(data, "scheduled_end_utc")
    if scheduled_end_utc <= scheduled_start_utc:
        raise bad_request("scheduled_end_utc must be strictly after scheduled_start_utc")
    forecast_attendance = req_int(data, "forecast_attendance", minimum=0)
    direct_supply_cost_cents = opt_int(data, "direct_supply_cost_cents", minimum=0, default=0)
    offering = get_or_404("offering", offering_id)
    room = get_or_404("room", room_id)
    if forecast_attendance > offering["max_participants_per_session"]:
        raise bad_request("forecast_attendance exceeds the offering roster cap")
    terminal(offering["status"] == "CLOSED")
    contract = find("contract", offering["contract_id"])
    require_contract_active(contract)
    if offering["status"] != "ACTIVE":
        raise ApiError("ERR_OFFERING_NOT_ACTIVE", 409)
    if room["room_state"] != "OPEN":
        raise ApiError("ERR_ROOM_NOT_OPEN", 422)
    if room["contract_id"] != offering["contract_id"]:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    if _room_conflict(room_id, scheduled_start_utc, scheduled_end_utc):
        raise ApiError("ERR_ROOM_TIME_CONFLICT", 409)
    if scheduled_start_utc < now():
        raise ApiError("ERR_SESSION_OUT_OF_TERM", 422)
    if scheduled_start_utc.date() < to_date(contract["term_start_on"]) or \
            scheduled_end_utc.date() > to_date(contract["term_end_on"]):
        raise ApiError("ERR_SESSION_OUT_OF_TERM", 422)
    if forecast_attendance > room["max_occupancy"]:
        raise ApiError("ERR_ROOM_OCCUPANCY_EXCEEDED", 422)
    minutes = int((scheduled_end_utc - scheduled_start_utc).total_seconds() // 60)
    session = new_record("session", {
        "offering_id": offering_id,
        "room_id": room_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "scheduled_minutes": minutes,
        "forecast_attendance": forecast_attendance,
        "direct_supply_cost_cents": direct_supply_cost_cents,
        "status": "SCHEDULED",
        "actual_attendance": 0,
        "cancel_reason": None,
        "started_at": None,
        "completed_at": None,
    })
    cascades.refresh_attainment(offering, provisional=True, final=False)
    return created(view(session))


@bp.post("/program-sessions/<sid>/status-changes")
def session_status_change(sid):
    require(ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_OPERATOR_ADMIN)
    session = get_or_404("session", sid)
    data = body()
    action = req_enum(data, "action", ("START", "COMPLETE", "CANCEL"))
    cancel_reason = opt_enum(data, "cancel_reason",
                             ("NO_COVER", "CLIENT_REQUEST", "FACILITY"))
    if action == "CANCEL" and cancel_reason is None:
        raise bad_request("cancel_reason is required on the cancel branch")
    terminal(session["status"] in SESSION_TERMINAL)
    offering = find("offering", session["offering_id"])
    contract = find("contract", offering["contract_id"]) if offering else None
    if action == "START":
        if session["status"] != "STAFFED":
            raise ApiError("ERR_SESSION_NOT_STAFFED", 409)
        require_contract_active(contract)
        if not calc.contract_has_ready_aed(offering["contract_id"]):
            raise ApiError("ERR_AED_NOT_READY", 422)
        room = find("room", session["room_id"])
        if room is None or room["room_state"] != "OPEN":
            raise ApiError("ERR_ROOM_NOT_OPEN", 422)
        if now() < session["scheduled_start_utc"] - timedelta(minutes=START_GRACE_MINUTES):
            raise ApiError("ERR_SESSION_START_TOO_EARLY", 422)
        upd(session, status="IN_PROGRESS", started_at=now())
        cascades.refresh_attainment(offering, provisional=True, final=False)
    elif action == "COMPLETE":
        if session["status"] != "IN_PROGRESS":
            invalid_transition()
        counted = len([p for p in where("participation", session_id=session["id"])
                       if p["status"] == "COUNTED"])
        upd(session, status="COMPLETED", completed_at=now(), actual_attendance=counted)
        for assignment in where("assignment", session_id=session["id"]):
            if assignment["status"] != "CONFIRMED":
                continue
            staff = find("staff", assignment["staff_member_id"])
            cost = 0
            if staff is not None:
                cost = calc.assignment_labor_cost(staff, assignment["paid_minutes"])
            upd(assignment, status="COMPLETED", labor_cost_cents=cost)
        cascades.refresh_attainment(offering, provisional=True, final=True)
    else:
        if session["status"] not in calc.OPEN_SESSION_STATUSES:
            invalid_transition()
        if cancel_reason == "NO_COVER" and cascades.has_live_lead(session):
            invalid_transition()
        cascades.cancel_session(session, cancel_reason)
    return ok(view(session))
