"""MobilityProgram endpoints (PRD §3.1)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import get_one, public
from services.core import new_record
from validate import get_body, opt_int, req_str

bp = Blueprint("programs", __name__)


@bp.post("/mobility/programs")
def create_program():
    authorized(["MobilityAdmin"])
    body = get_body()
    rec = new_record("programs", {
        "name": req_str(body, "name"),
        "home_country_code": req_str(body, "home_country_code"),
        "functional_currency": body.get("functional_currency") if isinstance(body.get("functional_currency"), str) and body.get("functional_currency") else "USD",
        "cost_overrun_threshold_pct": opt_int(body, "cost_overrun_threshold_pct", 110),
        "max_assignment_duration_days": opt_int(body, "max_assignment_duration_days", 1825),
        "per_diem_annual_day_cap": opt_int(body, "per_diem_annual_day_cap", 365),
        "status": "ACTIVE",
        "total_posted_chargeback_cents": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/programs/<rid>")
def get_program(rid):
    return get_one("programs", rid)
