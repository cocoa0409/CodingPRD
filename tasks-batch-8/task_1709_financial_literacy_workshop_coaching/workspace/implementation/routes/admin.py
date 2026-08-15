"""Clock, curriculum modules, coaches, participants."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, logical_now, set_logical_clock
from errors import ApiError
from helpers import body, fmt_dt, invalid, req_datetime, req_int, req_str
from middleware import ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT, forbidden, require_roles
from response import ok
from services.domain import (
    CERT_TTL,
    OPEN_CASE_STATUSES,
    exit_case,
    incentive_summary,
    new_common,
    ser_coach,
    ser_module,
    ser_participant,
    stall_cascade,
    sweep_all,
    sweep_coach,
    touch,
)

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(ROLE_ADMIN)
    data = body()
    to_dt = req_datetime(data, "to_iso8601")
    set_logical_clock(to_dt)
    sweep_all()
    return ok({"current_utc": fmt_dt(logical_now())}, 200)


# ---------------------------------------------------------------------------
# Curriculum modules
# ---------------------------------------------------------------------------

@bp.post("/curriculum-modules")
def create_module():
    require_roles(ROLE_ADMIN)
    data = body()
    module_code = req_str(data, "module_code")
    title = req_str(data, "title")
    session_count = req_int(data, "session_count", minimum=1)
    rate = req_int(data, "incentive_cents_per_hour", minimum=0)
    bonus = req_int(data, "completion_bonus_cents", minimum=0)
    threshold = req_int(data, "completion_threshold", minimum=1)
    if threshold > session_count:
        invalid("Field 'completion_threshold' must be <= 'session_count'.")
    if any(m["module_code"] == module_code for m in STORE["modules"].values()):
        raise ApiError("ERR_MODULE_CODE_TAKEN", "module_code already in use.", 409)
    rec = new_common()
    rec.update(
        {
            "module_code": module_code,
            "title": title,
            "session_count": session_count,
            "incentive_cents_per_hour": rate,
            "completion_bonus_cents": bonus,
            "completion_threshold": threshold,
            "status": "ACTIVE",
        }
    )
    STORE["modules"][rec["id"]] = rec
    return ok(ser_module(rec), 201)


@bp.get("/curriculum-modules/<mid>")
def get_module(mid):
    require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["modules"].get(mid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Curriculum module not found.", 404)
    return ok(ser_module(rec), 200)


@bp.post("/curriculum-modules/<mid>/retire")
def retire_module(mid):
    require_roles(ROLE_ADMIN)
    rec = STORE["modules"].get(mid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Curriculum module not found.", 404)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE module can be retired.", 409)
    rec["status"] = "RETIRED"
    touch(rec)
    return ok(ser_module(rec), 200)


# ---------------------------------------------------------------------------
# Coaches
# ---------------------------------------------------------------------------

@bp.post("/coaches")
def create_coach():
    require_roles(ROLE_ADMIN)
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    max_caseload = req_int(data, "max_caseload", minimum=1)
    if any(c["email"] == email for c in STORE["coaches"].values()):
        raise ApiError("ERR_DUPLICATE_EMAIL", "Email already in use by a coach.", 409)
    rec = new_common()
    rec.update(
        {
            "full_name": full_name,
            "email": email,
            "max_caseload": max_caseload,
            "status": "CANDIDATE",
            "certification_expires_at": None,
        }
    )
    STORE["coaches"][rec["id"]] = rec
    return ok(ser_coach(rec), 201)


def _load_coach(cid):
    rec = STORE["coaches"].get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Coach not found.", 404)
    sweep_coach(rec)
    return rec


@bp.get("/coaches/<cid>")
def get_coach(cid):
    require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = _load_coach(cid)
    return ok(ser_coach(rec), 200)


@bp.post("/coaches/<cid>/certify")
def certify_coach(cid):
    require_roles(ROLE_ADMIN)
    rec = _load_coach(cid)
    if rec["status"] != "CANDIDATE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a CANDIDATE coach can be certified.", 409
        )
    rec["status"] = "CERTIFIED"
    rec["certification_expires_at"] = logical_now() + CERT_TTL
    touch(rec)
    return ok(ser_coach(rec), 200)


@bp.post("/coaches/<cid>/suspend")
def suspend_coach(cid):
    require_roles(ROLE_ADMIN)
    rec = _load_coach(cid)
    if rec["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a CERTIFIED coach can be suspended.", 409
        )
    rec["status"] = "SUSPENDED"
    touch(rec)
    stall_cascade(rec["id"])
    return ok(ser_coach(rec), 200)


@bp.post("/coaches/<cid>/reinstate")
def reinstate_coach(cid):
    require_roles(ROLE_ADMIN)
    rec = _load_coach(cid)
    if rec["status"] not in ("SUSPENDED", "LAPSED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUSPENDED or LAPSED coach can be reinstated.",
            409,
        )
    rec["status"] = "CERTIFIED"
    rec["certification_expires_at"] = logical_now() + CERT_TTL
    touch(rec)
    return ok(ser_coach(rec), 200)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

@bp.post("/participants")
def create_participant():
    require_roles(ROLE_ADMIN)
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    income = req_int(data, "annual_income_cents", minimum=0)
    if any(p["email"] == email for p in STORE["participants"].values()):
        raise ApiError(
            "ERR_DUPLICATE_EMAIL", "Email already in use by a participant.", 409
        )
    rec = new_common()
    rec.update(
        {
            "full_name": full_name,
            "email": email,
            "annual_income_cents": income,
            "status": "ACTIVE",
            "no_show_count": 0,
        }
    )
    STORE["participants"][rec["id"]] = rec
    return ok(ser_participant(rec), 201)


def _load_participant(pid):
    rec = STORE["participants"].get(pid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Participant not found.", 404)
    return rec


@bp.get("/participants/<pid>")
def get_participant(pid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    if role == ROLE_PARTICIPANT and pid != uid:
        forbidden("Participants may read only their own record.")
    rec = _load_participant(pid)
    return ok(ser_participant(rec), 200)


@bp.post("/participants/<pid>/clear-restriction")
def clear_restriction(pid):
    require_roles(ROLE_ADMIN)
    rec = _load_participant(pid)
    if rec["status"] != "RESTRICTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a RESTRICTED participant can be cleared.",
            409,
        )
    rec["status"] = "ACTIVE"
    rec["no_show_count"] = 0
    touch(rec)
    return ok(ser_participant(rec), 200)


@bp.post("/participants/<pid>/exit")
def exit_participant(pid):
    require_roles(ROLE_ADMIN)
    rec = _load_participant(pid)
    if rec["status"] not in ("ACTIVE", "RESTRICTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE or RESTRICTED participant can exit.",
            409,
        )
    rec["status"] = "EXITED"
    touch(rec)
    for case in list(STORE["cases"].values()):
        if case["participant_id"] == pid and case["status"] in OPEN_CASE_STATUSES:
            exit_case(case)
    return ok(ser_participant(rec), 200)


@bp.get("/participants/<pid>/incentive-summary")
def get_incentive_summary(pid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    if role == ROLE_PARTICIPANT and pid != uid:
        forbidden("Participants may read only their own incentive summary.")
    _load_participant(pid)
    return ok(incentive_summary(pid), 200)
