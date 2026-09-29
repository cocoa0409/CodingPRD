"""DiscretionaryAdjustment routes: the plan-level discretionary budget draw."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, FINANCE_CONTROLLER,
                        HR_BUSINESS_PARTNER, PLAN_ADMIN, authenticate,
                        bad_request, get_body, opt_string, query_param,
                        req_enum, req_id, req_int, req_string)
from response import object_response
from routes.common import paginated
from serialize import adjustment_out
from services import calc, lookup, rollup

bp = Blueprint("adjustments", __name__)

READ_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, HR_BUSINESS_PARTNER,
              FINANCE_CONTROLLER]
DECISIONS = {"APPROVE", "REJECT"}
ALLOCATION_STATUSES = ("ALLOCATION_OPEN", "CALIBRATION_REVIEW")
ELIGIBLE_FOR_MONEY = ("ELIGIBLE", "GOOD_LEAVER")


@bp.route("/discretionary-adjustments", methods=["POST"])
def create_adjustment():
    caller = authenticate([PLAN_ADMIN, HR_BUSINESS_PARTNER])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    award_id = req_id(body, "award_id")
    adjustment_cents = req_int(body, "adjustment_cents")
    justification = req_string(body, "justification", min_length=1)
    documentation_ref = opt_string(body, "documentation_ref")
    expected_plan_version = req_int(body, "expected_plan_version")
    if adjustment_cents == 0:
        raise bad_request("Field 'adjustment_cents' must be a non-zero integer")

    plan = lookup.plan(plan_id)
    award = lookup.award(award_id)

    if plan["status"] not in ALLOCATION_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    pool = db.bu_pools.get(award["bu_pool_id"])
    if pool is None or pool["calibration_status"] not in ("FUNDED", "ALLOCATING"):
        raise ApiError("ERR_POOL_NOT_ALLOCATING")
    if award["allocation_status"] not in ("PROPOSED", "CALIBRATED"):
        raise ApiError("ERR_AWARD_STATE_INVALID",
                       "An adjustment requires an award in PROPOSED or CALIBRATED")
    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION")
    if abs(adjustment_cents) > calc.DOC_REQUIRED_ABOVE_CENTS \
            and not (documentation_ref or "").strip():
        raise ApiError("ERR_ADJUSTMENT_DOCUMENTATION_REQUIRED")
    if award["plan_id"] != plan_id:
        raise ApiError("ERR_PLAN_SCOPE_MISMATCH",
                       "The award belongs to a different plan")
    if award["eligibility_status"] not in ELIGIBLE_FOR_MONEY:
        raise ApiError("ERR_AWARD_NOT_ELIGIBLE")

    adjustment = db.base_record()
    adjustment.update({
        "plan_id": plan_id,
        "award_id": award_id,
        "adjustment_cents": adjustment_cents,
        "justification": justification,
        "documentation_ref": documentation_ref,
        "per_award_cap_cents": calc.per_award_cap_cents(
            award["prorated_target_cents"]),
        "status": "PENDING_APPROVAL",
        "submitted_by_user_id": caller.user_id,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.discretionary_adjustments[adjustment["id"]] = adjustment
    return object_response(adjustment_out(adjustment), 201)


def _apply_money(plan, award):
    rollup.refresh_award_adjustment_total(award)
    db.touch(award)
    pool = db.bu_pools.get(award["bu_pool_id"])
    if pool is not None:
        pool_before = db.snapshot(pool)
        rollup.recompute_pool(pool, bump=False)
        db.bump_if_changed(pool, pool_before)
    plan_before = db.snapshot(plan)
    rollup.refresh_discretionary_used(plan)
    rollup.apply_plan_governance(plan)
    db.bump_if_changed(plan, plan_before)


@bp.route("/discretionary-adjustments/<adjustment_id>/decision", methods=["POST"])
def decide_adjustment(adjustment_id):
    caller = authenticate([COMPENSATION_COMMITTEE])
    adjustment = lookup.adjustment(adjustment_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    decision_note = opt_string(body, "decision_note")

    plan = lookup.plan(adjustment["plan_id"])
    award = lookup.award(adjustment["award_id"])

    if plan["status"] not in ALLOCATION_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    if adjustment["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_ADJUSTMENT_NOT_PENDING",
                       "A decision requires an adjustment in PENDING_APPROVAL")
    if adjustment["submitted_by_user_id"] is not None \
            and caller.user_id == adjustment["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitter may not decide their own adjustment")

    amount = adjustment["adjustment_cents"]
    if decision == "APPROVE":
        if award["final_award_cents"] + amount < 0:
            raise ApiError("ERR_NEGATIVE_AWARD_NOT_ALLOWED")
        if abs(amount) > adjustment["per_award_cap_cents"]:
            raise ApiError("ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT")
        if plan["discretionary_used_cents"] + abs(amount) \
                > plan["discretionary_budget_cents"]:
            raise ApiError("ERR_DISCRETIONARY_BUDGET_EXCEEDED")

        adjustment["status"] = "APPROVED"
        adjustment["decided_by_user_id"] = caller.user_id
        adjustment["decision_note"] = decision_note
        db.touch(adjustment)
        _apply_money(plan, award)
    else:
        adjustment["status"] = "REJECTED"
        adjustment["decided_by_user_id"] = caller.user_id
        adjustment["decision_note"] = decision_note
        db.touch(adjustment)

    return object_response(adjustment_out(adjustment))


@bp.route("/discretionary-adjustments/<adjustment_id>/reverse", methods=["POST"])
def reverse_adjustment(adjustment_id):
    authenticate([COMPENSATION_COMMITTEE])
    adjustment = lookup.adjustment(adjustment_id)
    body = get_body()
    decision_note = req_string(body, "decision_note")

    plan = lookup.plan(adjustment["plan_id"])
    award = lookup.award(adjustment["award_id"])

    if plan["status"] not in ALLOCATION_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    if adjustment["status"] != "APPROVED":
        raise ApiError("ERR_ADJUSTMENT_NOT_PENDING",
                       "A reversal requires an adjustment in APPROVED")

    adjustment["status"] = "REVERSED"
    adjustment["decision_note"] = decision_note
    db.touch(adjustment)
    _apply_money(plan, award)
    return object_response(adjustment_out(adjustment))


@bp.route("/discretionary-adjustments/<adjustment_id>", methods=["GET"])
def get_adjustment(adjustment_id):
    authenticate(READ_ROLES)
    return object_response(adjustment_out(lookup.adjustment(adjustment_id)))


@bp.route("/discretionary-adjustments", methods=["GET"])
def list_adjustments():
    authenticate(READ_ROLES)
    records = db.ordered(db.discretionary_adjustments)
    for param in ("plan_id", "award_id", "status"):
        value = query_param(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return paginated(records, adjustment_out)
