"""State-law applicability monitoring runs and evaluation records."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_evaluation
from utils import is_num, round_half_up_2

bp = Blueprint("applicability", __name__)


@bp.post("/privacy/applicability-evaluations/run")
def run_applicability_evaluation():
    require_roles("PrivacyAdmin")
    body = get_body()
    state_revenues = body.get("state_revenues")
    total_revenue_cents = body.get("total_revenue_cents")
    if (not isinstance(state_revenues, dict)
            or any(not isinstance(k, str) or not is_num(v) or v < 0
                   for k, v in state_revenues.items())):
        raise ApiError("ERR_INVALID_REQUEST",
                       "state_revenues must be an object mapping state codes to non-negative cent amounts")
    if not is_num(total_revenue_cents) or total_revenue_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "total_revenue_cents must be a non-negative number")
    total = Decimal(str(total_revenue_cents))
    rules = sorted(db.state_law_rules.values(),
                   key=lambda r: (r["created_at"], r["state_code"]))
    run_id = db.new_id()
    now = clock.now()
    count_created = 0
    for rule in rules:
        resident_count = sum(1 for c in db.consumers.values()
                             if c["state_code"] == rule["state_code"])
        state_rev = state_revenues.get(rule["state_code"], 0)
        if total > 0:
            # Pinned order: divide raw cent totals, multiply by 100, then
            # round_half_up once to two decimals. No truncation.
            share = round_half_up_2(
                (Decimal(str(state_rev)) / total) * Decimal(100))
        else:
            share = Decimal("0.00")
        applies = (resident_count >= rule["resident_records_threshold"]
                   or share >= Decimal(str(rule["revenue_share_threshold_pct"])))
        evaluation = {
            "id": db.new_id(),
            "created_at": now,
            "state_law_rule_id": rule["id"],
            "evaluation_run_id": run_id,
            "resident_consumer_count": resident_count,
            "revenue_share_pct": float(share),
            "applies": bool(applies),
            "margin_to_threshold": resident_count - rule["resident_records_threshold"],
            "_seq": next(db.evaluation_seq),
        }
        db.evaluations[evaluation["id"]] = evaluation
        count_created += 1
    return success({
        "evaluation_run_id": run_id,
        "evaluation_count": count_created,
    }, 201)


@bp.get("/privacy/applicability-evaluations")
def list_applicability_evaluations():
    require_roles(*STAFF_ROLES)
    items = sorted(db.evaluations.values(), key=lambda e: e["_seq"])
    state_law_rule_id = request.args.get("state_law_rule_id")
    evaluation_run_id = request.args.get("evaluation_run_id")
    if state_law_rule_id is not None:
        items = [e for e in items if e["state_law_rule_id"] == state_law_rule_id]
    if evaluation_run_id is not None:
        items = [e for e in items if e["evaluation_run_id"] == evaluation_run_id]
    return list_response(items, ser_evaluation)


@bp.get("/privacy/applicability-evaluations/<evaluation_id>")
def get_applicability_evaluation(evaluation_id):
    require_roles(*STAFF_ROLES)
    evaluation = db.evaluations.get(evaluation_id)
    if evaluation is None:
        raise ApiError("ERR_NOT_FOUND", "applicability evaluation not found")
    return success(ser_evaluation(evaluation), 200)
