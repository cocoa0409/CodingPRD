"""PayrollHandoff endpoints (PRD §3.9)."""

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import store, clock
from errors import (ApiError, ERR_HANDOFF_NOT_FOUND,
                    ERR_INVALID_HANDOFF_STATE, ERR_CASE_TERMINAL,
                    ERR_INVALID_CASE_PHASE)
from helpers import touch, get_or_404, ser_handoff
from util import success, get_body, req_present, as_str, fmt_dt

bp = Blueprint("handoffs", __name__)

TRANSMIT_PHASES = ("DAY_ONE_READY", "IN_PROGRESS", "PROBATION")


@bp.get("/api/payroll-handoffs/<hid>")
def get_handoff(hid):
    require_roles(*ALL_ROLES)
    rec = get_or_404("handoffs", hid, ERR_HANDOFF_NOT_FOUND,
                     "PayrollHandoff")
    return success(ser_handoff(rec))


@bp.post("/api/payroll-handoffs/<hid>/transmit")
def transmit_handoff(hid):
    require_roles("HRAdmin")
    get_body()
    h = get_or_404("handoffs", hid, ERR_HANDOFF_NOT_FOUND, "PayrollHandoff")
    # Child state gate first, then the owning case's phase gate (PRD §3.9)
    if h["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_HANDOFF_STATE, 409,
                       "transmit requires a DRAFT handoff")
    case = store["cases"].get(h["case_id"])
    if case is not None:
        if case["phase"] in ("COMPLETED", "WITHDRAWN", "REVOKED",
                             "SEPARATED"):
            raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
        if case["phase"] not in TRANSMIT_PHASES:
            raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                           "transmit requires case phase DAY_ONE_READY, "
                           "IN_PROGRESS, or PROBATION")
    now = clock.current
    h["status"] = "TRANSMITTED"
    h["_transmitted_dt"] = now
    h["transmitted_at"] = fmt_dt(now)
    touch(h)
    return success(ser_handoff(h))


@bp.post("/api/payroll-handoffs/<hid>/acknowledge")
def acknowledge_handoff(hid):
    require_roles("PayrollOps")
    get_body()
    h = get_or_404("handoffs", hid, ERR_HANDOFF_NOT_FOUND, "PayrollHandoff")
    if h["status"] != "TRANSMITTED":
        raise ApiError(ERR_INVALID_HANDOFF_STATE, 409,
                       "acknowledge requires a TRANSMITTED handoff")
    now = clock.current
    h["status"] = "ACKNOWLEDGED"
    h["_ack_dt"] = now
    h["acknowledged_at"] = fmt_dt(now)
    # Boundary pinned: acknowledgement exactly at the window end is NOT a
    # breach; strictly later is.
    h["benefits_window_breached"] = now > h["_window_end_dt"]
    touch(h)
    return success(ser_handoff(h))


@bp.post("/api/payroll-handoffs/<hid>/reject")
def reject_handoff(hid):
    require_roles("PayrollOps")
    body = get_body()
    reason = as_str(req_present(body, "reason"), "reason")
    h = get_or_404("handoffs", hid, ERR_HANDOFF_NOT_FOUND, "PayrollHandoff")
    if h["status"] != "TRANSMITTED":
        raise ApiError(ERR_INVALID_HANDOFF_STATE, 409,
                       "reject requires a TRANSMITTED handoff")
    h["status"] = "REJECTED_BY_PAYROLL"
    h["rejection_reason"] = reason
    touch(h)
    return success(ser_handoff(h))


@bp.post("/api/payroll-handoffs/<hid>/withdraw")
def withdraw_handoff(hid):
    require_roles("HRAdmin")
    get_body()
    h = get_or_404("handoffs", hid, ERR_HANDOFF_NOT_FOUND, "PayrollHandoff")
    if h["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_HANDOFF_STATE, 409,
                       "withdraw requires a DRAFT handoff")
    h["status"] = "WITHDRAWN"
    touch(h)
    return success(ser_handoff(h))
