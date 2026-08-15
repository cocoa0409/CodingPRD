"""ASP rate schedule endpoints (PRD 3.3)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, get_body, list_response, one, public, read_all,
    req_date, req_int, req_str, stamp_new,
)
from services.sweep import activate_schedule
from util import CLOCK, new_id

bp = Blueprint("asp_schedules", __name__)


@bp.post("/api/asp-schedules")
def create_schedule():
    authorized(["PlanAdmin"])
    body = get_body()
    # ---- shape (stage 4) ----
    drug_id = req_str(body, "drug_id")
    effective_start = req_date(body, "effective_start")
    asp_rate_cents = req_int(body, "asp_rate_cents")
    if asp_rate_cents <= 0:
        raise_error(ERR_INVALID_REQUEST, "asp_rate_cents must be > 0")
    # ---- existence (stage 5) ----
    if drug_id not in db["drugs"]:
        raise_error(ERR_NOT_FOUND, f"drug {drug_id} does not exist")
    born_effective = effective_start <= CLOCK.today()
    rec = {
        "id": new_id(),
        "drug_id": drug_id,
        "effective_start": effective_start.isoformat(),
        "asp_rate_cents": asp_rate_cents,
        "status": "EFFECTIVE" if born_effective else "SCHEDULED",
    }
    stamp_new(rec)
    db["asp_schedules"][rec["id"]] = rec
    if born_effective:
        # immediate activation: supersede the drug's other EFFECTIVE schedules
        # and run the asp_retro_repricing cascade
        activate_schedule(rec)
    return success_object(public(rec), 201)


@bp.get("/api/asp-schedules")
def list_schedules():
    read_all()
    items = list(db["asp_schedules"].values())
    items = apply_filters(items, ["drug_id", "status"])
    return list_response(items)


@bp.get("/api/asp-schedules/<scheduleId>")
def get_schedule(scheduleId):
    read_all()
    return one("asp_schedules", scheduleId)
