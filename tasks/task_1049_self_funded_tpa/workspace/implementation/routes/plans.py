from flask import Blueprint

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, touch, now_dt, parse_dt, add_days
from envelope import ok, created
from validation import (
    get_body, require_str, require_date, require_int_nonneg, require_ratio,
    optional_int_nonneg,
)

bp = Blueprint("plans", __name__)


@bp.post("/plans")
def create_plan():
    require_auth({"TPAAdmin"})
    body = get_body()
    p = {
        "id": new_id(),
        "sponsor_name": require_str(body, "sponsor_name"),
        "sponsor_tax_id": require_str(body, "sponsor_tax_id"),
        "plan_year_start": require_date(body, "plan_year_start"),
        "plan_year_end": require_date(body, "plan_year_end"),
        "individual_deductible_cents": require_int_nonneg(body, "individual_deductible_cents"),
        "oop_max_cents": require_int_nonneg(body, "oop_max_cents"),
        "plan_coinsurance_pct": require_ratio(body, "plan_coinsurance_pct"),
        "run_out_days": optional_int_nonneg(body, "run_out_days", 90),
        "terminated_at": None,
        "status": "ACTIVE",
    }
    stamp_new(p)
    db.plans[p["id"]] = p
    return created(serializers.plan(p))


@bp.get("/plans/<pid>")
def get_plan(pid):
    require_auth(ANY_ROLE)
    p = db.plans.get(pid)
    if not p:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    return ok(serializers.plan(p))


@bp.post("/plans/<pid>/terminate")
def terminate_plan(pid):
    require_auth({"TPAAdmin"})
    p = db.plans.get(pid)
    if not p:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    body = get_body()
    term_date = require_date(body, "termination_date")
    if p["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_STATE, "Plan is not ACTIVE")
    p["terminated_at"] = term_date
    p["status"] = "TERMINATED"
    touch(p)
    return ok(serializers.plan(p))


@bp.post("/plans/<pid>/close")
def close_plan(pid):
    require_auth({"TPAAdmin"})
    p = db.plans.get(pid)
    if not p:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    if p["status"] != "TERMINATED":
        fail(errors.ERR_INVALID_STATE, "Plan is not TERMINATED")
    deadline = add_days(parse_dt(p["terminated_at"]), p["run_out_days"])
    if not (now_dt() > deadline):
        fail(errors.ERR_INVALID_STATE, "Run-out window has not yet elapsed")
    p["status"] = "CLOSED"
    touch(p)
    return ok(serializers.plan(p))
