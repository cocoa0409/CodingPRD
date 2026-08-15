"""Establishment monthly hour-log endpoints (PRD §3.7)."""
from flask import Blueprint

from db import STORE
from errors import (raise_error, ERR_DUPLICATE, ERR_INVALID_STATE,
                    ERR_SUMMARY_LOCKED, ERR_INVALID_REQUEST)
from middleware import get_auth, require_roles, RATES_READ_ROLES
from response import success_object
from services.core import (get_body, req_str, req_int, base_fields, bump,
                           serialize, lookup, recompute_current_year_hours)

bp = Blueprint("hour_logs", __name__)

RKC = ("RecordkeepingCoordinator",)


@bp.post("/safety/hour-logs")
def create_hour_log():
    auth = get_auth()
    require_roles(auth, RKC)
    data = get_body()
    establishment_id = req_str(data, "establishment_id")
    year = req_int(data, "year")
    month = req_int(data, "month")
    if month < 1 or month > 12:
        raise_error(ERR_INVALID_REQUEST, "month must be in 1..12")
    hours_worked = req_int(data, "hours_worked", minimum=0)
    employment_count = req_int(data, "employment_count", minimum=0)
    lookup(STORE.establishments, establishment_id)
    if any(h["establishment_id"] == establishment_id and h["year"] == year
           and h["month"] == month for h in STORE.hour_logs.values()):
        raise_error(ERR_DUPLICATE,
                    "An hour log already exists for this "
                    "establishment-year-month")
    log = base_fields()
    log.update({
        "establishment_id": establishment_id,
        "year": year,
        "month": month,
        "hours_worked": hours_worked,
        "employment_count": employment_count,
        "status": "DRAFT",
        "approved_by": None,
    })
    STORE.hour_logs[log["id"]] = log
    return success_object(serialize(log), status=201)


@bp.get("/safety/hour-logs/<hourLogId>")
def get_hour_log(hourLogId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    log = lookup(STORE.hour_logs, hourLogId)
    return success_object(serialize(log))


@bp.post("/safety/hour-logs/<hourLogId>/approve")
def approve_hour_log(hourLogId):
    auth = get_auth()
    require_roles(auth, RKC)
    log = lookup(STORE.hour_logs, hourLogId)
    if log["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    log["status"] = "APPROVED"
    log["approved_by"] = auth.user_id
    bump(log)
    est = STORE.establishments.get(log["establishment_id"])
    if est:
        recompute_current_year_hours(est)
    return success_object(serialize(log))


@bp.post("/safety/hour-logs/<hourLogId>/reopen")
def reopen_hour_log(hourLogId):
    auth = get_auth()
    require_roles(auth, RKC)
    log = lookup(STORE.hour_logs, hourLogId)
    if log["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    for s in STORE.summaries.values():
        if (s["establishment_id"] == log["establishment_id"]
                and s["year"] == log["year"]
                and s["status"] in ("PREPARED", "CERTIFIED", "POSTED")):
            raise_error(ERR_SUMMARY_LOCKED,
                        "An annual summary for this establishment-year is "
                        "PREPARED or beyond")
    log["status"] = "DRAFT"
    log["approved_by"] = None
    bump(log)
    est = STORE.establishments.get(log["establishment_id"])
    if est:
        recompute_current_year_hours(est)
    return success_object(serialize(log))
