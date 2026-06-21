from flask import Blueprint

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_path
from services import calc, serialize
from util import get_json_body, parse_dt, parse_iso, touch

bp = Blueprint("floor_plan_lines", __name__)


@bp.get("/floor-plan-lines/<lid>")
@require_roles("InventoryClerk", "FinanceManager")
def get_line(lid):
    rec = get_path(db.floor_plan_lines, lid)
    return response.success(serialize.floor_plan_line(rec))


@bp.post("/floor-plan-lines/<lid>/curtailments")
@require_roles("InventoryClerk")
def record_curtailment(lid):
    rec = get_path(db.floor_plan_lines, lid)
    body = get_json_body()
    as_of = parse_dt(body, "as_of_date")
    floored_on = parse_iso(rec["floored_on"], "floored_on")
    age_days = calc.curtailment_age_days(floored_on, as_of)
    if age_days < calc.CURTAILMENT_AGE_DAYS:
        raise err("ERR_CURTAILMENT_NOT_DUE", "Curtailment not yet due")
    reduction = calc.curtailment_reduction(rec["principal_cents"])
    rec["principal_outstanding_cents"] -= reduction
    rec["curtailments_applied"] += 1
    touch(rec)
    return response.success(serialize.floor_plan_line(rec))


@bp.post("/floor-plan-lines/<lid>/payoff-quote")
@require_roles("InventoryClerk", "FinanceManager")
def payoff_quote(lid):
    rec = get_path(db.floor_plan_lines, lid)
    body = get_json_body()
    as_of = parse_dt(body, "as_of_date")
    floored_on = parse_iso(rec["floored_on"], "floored_on")
    days = calc.payoff_days(floored_on, as_of)
    interest = calc.floor_plan_interest(rec["principal_outstanding_cents"], rec["annual_rate_bps"], days)
    payoff = rec["principal_outstanding_cents"] + interest
    return response.success({
        "floor_plan_line_id": rec["id"],
        "days_accrued": days,
        "interest_cents": interest,
        "payoff_cents": payoff,
    })
