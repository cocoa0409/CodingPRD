"""Examination under oath endpoints (PRD §3.5).

Statutory notice: at least 10 full days between notice dispatch and the
scheduled start (exactly 10 days satisfies the window). Sessions occupy
half-open intervals [start, end); adjacency is allowed. A case-wide no-show
counter drives the EUO_NONAPPEARANCE claim hold at two no-shows.
"""

from __future__ import annotations

from flask import Blueprint

import db
from constants import EUO_ACTIVE, EUO_NOTICE_MIN_DAYS
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_EUO_NOTICE_WINDOW_VIOLATION,
    ERR_EUO_NOT_REQUIRED,
    ERR_EUO_TEMPORAL_CONFLICT,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_euo
from services.cascade import claim_euo_nonappearance
from services.scoring import has_admitted_evidence
from util import (
    apply_filters,
    child_or_404,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("euo", __name__)

INVESTIGATOR = ("SIUInvestigator",)
READERS = ("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")


def _resolve(caseId: str, euoId: str = None):
    case = path_or_404(db.cases, caseId, "SIUCase")
    session = None
    if euoId is not None:
        session = child_or_404(db.euo_sessions, euoId, "case_id", case["id"], "EUOSession")
    return case, session


def _overlaps_active(case_id: str, start, end, exclude_id: str = None) -> bool:
    """Half-open [start, end) overlap against active sessions of the case."""
    for row in db.euo_sessions.values():
        if row.get("case_id") != case_id or row.get("status") not in EUO_ACTIVE:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        existing_start = db.parse_instant(row.get("scheduled_start_at"))
        existing_end = db.parse_instant(row.get("scheduled_end_at"))
        if existing_start is None or existing_end is None:
            continue
        if start < existing_end and existing_start < end:
            return True
    return False


def _new_session(case: dict, start_raw: str, end_raw: str, location: str, attendee: str) -> dict:
    session = {
        "case_id": case["id"],
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "location": location,
        "insured_attendee_name": attendee,
        "status": "SCHEDULED",
        "notice_sent_at": None,
        "conducted_at": None,
        "transcript_received": False,
        "no_show_count": 0,
    }
    db.stamp_new(session)
    db.euo_sessions[session["id"]] = session
    return session


def _return_case_to_investigation(case: dict) -> None:
    if case.get("status") == "EUO_PENDING":
        case["status"] = "UNDER_INVESTIGATION"
        db.touch(case)


@bp.post("/siu/cases/<caseId>/euo-sessions")
@require_roles("SIUInvestigator")
def schedule_euo(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    start_raw = require_ts(body, "scheduled_start_at")
    end_raw = require_ts(body, "scheduled_end_at")
    location = require_string(body, "location")
    attendee = require_string(body, "insured_attendee_name")
    start = db.parse_instant(start_raw)
    end = db.parse_instant(end_raw)
    # The start must lie in the future (shape-level rule: 400).
    if start <= db.clock.now:
        raise_err(ERR_INVALID_REQUEST, "Field scheduled_start_at must be in the future")
    case, _ = _resolve(caseId)
    # Temporal coherence/non-overlap (priority 10) outranks the case-state and
    # euo_required checks: an overlapping second session is rejected with
    # ERR_EUO_TEMPORAL_CONFLICT even while the case is EUO_PENDING.
    if end <= start:
        raise_err(ERR_EUO_TEMPORAL_CONFLICT, "scheduled_end_at must be later than scheduled_start_at")
    if _overlaps_active(case["id"], start, end):
        raise_err(ERR_EUO_TEMPORAL_CONFLICT, "Window overlaps another active session for this case")
    # Scheduling is possible only from UNDER_INVESTIGATION.
    if case.get("status") != "UNDER_INVESTIGATION":
        raise_err(ERR_INVALID_STATE, "Case must be UNDER_INVESTIGATION to schedule an EUO")
    # Priority 13: the case must actually require an EUO. This outranks the
    # admitted-evidence precondition (the err_euo_not_required_trigger design
    # schedules on an evidence-less case and expects ERR_EUO_NOT_REQUIRED).
    if not case.get("euo_required"):
        raise_err(ERR_EUO_NOT_REQUIRED, "Case does not require an EUO")
    if not has_admitted_evidence(case["id"]):
        raise_err(ERR_INVALID_STATE, "At least one ADMITTED evidence item is required")

    session = _new_session(case, start_raw, end_raw, location, attendee)
    case["status"] = "EUO_PENDING"
    db.touch(case)
    return success_object(pub_euo(session), 201)


@bp.get("/siu/cases/<caseId>/euo-sessions")
@require_roles(*READERS)
def list_case_euos(caseId: str, _user_id: str, _role: str):
    case, _ = _resolve(caseId)
    limit, offset = parse_pagination()
    items = [s for s in db.euo_sessions.values() if s.get("case_id") == case["id"]]
    items = apply_filters(items, ["status"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_euo(s) for s in page], limit, offset, total)


@bp.get("/siu/euo-sessions")
@require_roles(*READERS)
def list_all_euos(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.euo_sessions.values()), ["case_id", "status"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_euo(s) for s in page], limit, offset, total)


@bp.get("/siu/euo-sessions/<euoId>")
@require_roles(*READERS)
def get_euo(euoId: str, _user_id: str, _role: str):
    session = path_or_404(db.euo_sessions, euoId, "EUOSession")
    return success_object(pub_euo(session))


@bp.get("/siu/cases/<caseId>/euo-sessions/<euoId>")
@require_roles(*READERS)
def get_case_euo(caseId: str, euoId: str, _user_id: str, _role: str):
    _, session = _resolve(caseId, euoId)
    return success_object(pub_euo(session))


@bp.post("/siu/cases/<caseId>/euo-sessions/<euoId>/send-notice")
@require_roles("SIUInvestigator")
def send_notice(caseId: str, euoId: str, _user_id: str, _role: str):
    get_json_body()
    _, session = _resolve(caseId, euoId)
    if session.get("status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Session must be SCHEDULED to send notice")
    start = db.parse_instant(session.get("scheduled_start_at"))
    # Statutory notice window: at least 10 full calendar days must remain before
    # the scheduled start; exactly 10 days satisfies the window (PRD §2.10).
    remaining_days = (start.date() - db.clock.now.date()).days
    if remaining_days < EUO_NOTICE_MIN_DAYS:
        raise_err(
            ERR_EUO_NOTICE_WINDOW_VIOLATION,
            "Notice requires at least 10 full days before the scheduled start",
        )
    session["status"] = "NOTICE_SENT"
    session["notice_sent_at"] = db.clock.now_string()
    db.touch(session)
    return success_object(pub_euo(session))


@bp.post("/siu/cases/<caseId>/euo-sessions/<euoId>/conduct")
@require_roles("SIUInvestigator")
def conduct_euo(caseId: str, euoId: str, _user_id: str, _role: str):
    get_json_body()
    case, session = _resolve(caseId, euoId)
    if session.get("status") != "NOTICE_SENT":
        raise_err(ERR_INVALID_STATE, "Session must be NOTICE_SENT to be conducted")
    if db.clock.now < db.parse_instant(session.get("scheduled_start_at")):
        raise_err(ERR_INVALID_STATE, "Session cannot be conducted before its scheduled start")
    session["status"] = "CONDUCTED"
    session["conducted_at"] = db.clock.now_string()
    session["transcript_received"] = True
    db.touch(session)
    _return_case_to_investigation(case)
    return success_object(pub_euo(session))


@bp.post("/siu/cases/<caseId>/euo-sessions/<euoId>/no-show")
@require_roles("SIUInvestigator")
def no_show_euo(caseId: str, euoId: str, _user_id: str, _role: str):
    get_json_body()
    case, session = _resolve(caseId, euoId)
    if session.get("status") != "NOTICE_SENT":
        raise_err(ERR_INVALID_STATE, "Session must be NOTICE_SENT to record a no-show")
    if db.clock.now < db.parse_instant(session.get("scheduled_end_at")):
        raise_err(ERR_INVALID_STATE, "No-show cannot be recorded before the scheduled end")
    total = int(case.get("_no_show_total", 0)) + 1
    case["_no_show_total"] = total
    session["status"] = "NO_SHOW"
    session["no_show_count"] = total
    db.touch(session)
    _return_case_to_investigation(case)
    if total >= 2:
        claim = db.claims.get(case.get("claim_id"))
        if claim is not None:
            claim_euo_nonappearance(claim)
    return success_object(pub_euo(session))


@bp.post("/siu/cases/<caseId>/euo-sessions/<euoId>/reschedule")
@require_roles("SIUInvestigator")
def reschedule_euo(caseId: str, euoId: str, _user_id: str, _role: str):
    body = get_json_body()
    start_raw = require_ts(body, "scheduled_start_at")
    end_raw = require_ts(body, "scheduled_end_at")
    location = require_string(body, "location")
    case, session = _resolve(caseId, euoId)
    if session.get("status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Session must be SCHEDULED to be rescheduled")
    if db.clock.now >= db.parse_instant(session.get("scheduled_start_at")):
        raise_err(ERR_INVALID_STATE, "Session cannot be rescheduled once its start has arrived")
    start = db.parse_instant(start_raw)
    end = db.parse_instant(end_raw)
    if end <= start:
        raise_err(ERR_EUO_TEMPORAL_CONFLICT, "scheduled_end_at must be later than scheduled_start_at")
    if _overlaps_active(case["id"], start, end, exclude_id=session["id"]):
        raise_err(ERR_EUO_TEMPORAL_CONFLICT, "Window overlaps another active session for this case")
    new_session = _new_session(case, start_raw, end_raw, location, session.get("insured_attendee_name"))
    session["status"] = "RESCHEDULED"
    db.touch(session)
    return success_object(pub_euo(new_session), 201)


@bp.post("/siu/cases/<caseId>/euo-sessions/<euoId>/cancel")
@require_roles("SIUManager")
def cancel_euo(caseId: str, euoId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    case, session = _resolve(caseId, euoId)
    if session.get("status") != "NOTICE_SENT":
        raise_err(ERR_INVALID_STATE, "Session must be NOTICE_SENT to be cancelled")
    if db.clock.now >= db.parse_instant(session.get("scheduled_start_at")):
        raise_err(ERR_INVALID_STATE, "Session cannot be cancelled once its start has arrived")
    session["status"] = "CANCELLED"
    db.touch(session)
    _return_case_to_investigation(case)
    return success_object(pub_euo(session))
