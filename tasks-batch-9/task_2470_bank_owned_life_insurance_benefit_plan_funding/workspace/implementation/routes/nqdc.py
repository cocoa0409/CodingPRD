"""Deferred compensation plans and participant liabilities (PRD 3.6)."""

from flask import Blueprint

import calc
from cascades import recompute_plan
from errors import ApiError
from response import collection_response, object_response, resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_employee,
    find_liability,
    find_plan,
    find_policy,
    get_enum,
    get_id,
    get_int,
    get_money,
    get_string,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("nqdc", __name__)

PLAN_TYPES = ("SERP", "DEFERRED_BONUS", "DIRECTOR_FEE")
PLAN_STATUSES = ("ACTIVE", "FROZEN", "TERMINATED")
LIABILITY_STATUSES = ("ACTIVE", "SETTLED")
BASES = ("ACCRUAL", "PBO")
READ_ROLES = ("TreasuryController", "RiskOfficer", "BoardSecretary")


# ---- plans --------------------------------------------------------------


@bp.post("/nqdc-plans")
def create_plan():
    authorize(("TreasuryController",))
    body = json_body()
    plan_name = get_string(body, "plan_name")
    plan_type = get_enum(body, "plan_type", PLAN_TYPES)
    discount_rate_bps = get_int(
        body, "discount_rate_bps", required=False, default=500, exclusive_minimum=0
    )
    plan = create_record(
        db.nqdc_plans,
        {
            "plan_name": plan_name,
            "plan_type": plan_type,
            "discount_rate_bps": discount_rate_bps,
            "status": "ACTIVE",
            "accrual_liability_usd": calc.ZERO,
            "pbo_liability_usd": calc.ZERO,
            "matched_cash_value_usd": calc.ZERO,
            "funding_posture": "FUNDED",
            "funded_ratio_bps": calc.FUNDED_MIN_BPS,
        },
    )
    return resource_response(plan, 201)


@bp.get("/nqdc-plans/<plan_id>")
def read_plan(plan_id):
    authorize(READ_ROLES)
    return resource_response(find_plan(plan_id))


@bp.get("/nqdc-plans/<plan_id>/funding-summary")
def funding_summary(plan_id):
    authorize(READ_ROLES)
    basis = query_enum("basis", BASES) or "ACCRUAL"
    plan = find_plan(plan_id)
    return object_response(calc.plan_view(plan, basis))


@bp.post("/nqdc-plans/<plan_id>/revalue")
def revalue_plan(plan_id):
    authorize(("TreasuryController",))
    plan = find_plan(plan_id)
    guard_terminal(plan["status"], ("TERMINATED",))
    guard_transition(plan["status"] in ("ACTIVE", "FROZEN"))
    recompute_plan(plan, freeze_if_critical=True)
    return resource_response(plan)


@bp.post("/nqdc-plans/<plan_id>/freeze")
def freeze_plan(plan_id):
    authorize(("TreasuryController",))
    plan = find_plan(plan_id)
    guard_terminal(plan["status"], ("TERMINATED",))
    guard_transition(plan["status"] == "ACTIVE")
    plan["status"] = "FROZEN"
    touch(plan)
    return resource_response(plan)


@bp.post("/nqdc-plans/<plan_id>/unfreeze")
def unfreeze_plan(plan_id):
    authorize(("TreasuryController",))
    plan = find_plan(plan_id)
    guard_terminal(plan["status"], ("TERMINATED",))
    guard_transition(plan["status"] == "FROZEN")
    fresh = calc.plan_view(plan, "ACCRUAL")
    guard_transition(fresh["funding_posture"] in ("FUNDED", "UNDERFUNDED"))
    recompute_plan(plan, freeze_if_critical=False, bump=False)
    plan["status"] = "ACTIVE"
    touch(plan)
    return resource_response(plan)


@bp.post("/nqdc-plans/<plan_id>/terminate")
def terminate_plan(plan_id):
    authorize(("TreasuryController",))
    plan = find_plan(plan_id)
    guard_terminal(plan["status"], ("TERMINATED",))
    guard_transition(plan["status"] == "FROZEN")
    outstanding = any(
        row["nqdc_plan_id"] == plan["id"] and row["status"] != "SETTLED"
        for row in db.nqdc_liabilities.values()
    )
    guard_transition(not outstanding)
    plan["status"] = "TERMINATED"
    touch(plan)
    return resource_response(plan)


# ---- participant liabilities -------------------------------------------


@bp.post("/nqdc-liabilities")
def create_liability():
    authorize(("TreasuryController",))
    body = json_body()
    nqdc_plan_id = get_id(body, "nqdc_plan_id")
    employee_id = get_id(body, "employee_id")
    matched_policy_id = get_id(body, "matched_policy_id", required=False)
    accrued = get_money(body, "accrued_to_date_usd")
    projected = get_money(body, "projected_benefit_usd", positive_only=True)
    years_to_payout = get_int(body, "years_to_payout", minimum=0)

    plan = find_plan(nqdc_plan_id)
    find_employee(employee_id)
    if matched_policy_id is not None:
        find_policy(matched_policy_id)
    guard_transition(plan["status"] == "ACTIVE")

    liability = create_record(
        db.nqdc_liabilities,
        {
            "nqdc_plan_id": plan["id"],
            "employee_id": employee_id,
            "matched_policy_id": matched_policy_id,
            "accrued_to_date_usd": accrued,
            "projected_benefit_usd": projected,
            "years_to_payout": years_to_payout,
            "discounted_benefit_usd": calc.ZERO,
            "status": "ACTIVE",
        },
    )
    liability["discounted_benefit_usd"] = calc.discounted_benefit(plan, liability)
    recompute_plan(plan, freeze_if_critical=False)
    return resource_response(liability, 201)


@bp.get("/nqdc-liabilities")
def list_liabilities():
    authorize(READ_ROLES)
    limit, offset = pagination()
    nqdc_plan_id = query_str("nqdc_plan_id")
    employee_id = query_str("employee_id")
    matched_policy_id = query_str("matched_policy_id")
    status = query_enum("status", LIABILITY_STATUSES)
    rows = []
    for liability in db.nqdc_liabilities.values():
        if nqdc_plan_id is not None and liability["nqdc_plan_id"] != nqdc_plan_id:
            continue
        if employee_id is not None and liability["employee_id"] != employee_id:
            continue
        if matched_policy_id is not None and liability.get("matched_policy_id") != matched_policy_id:
            continue
        if status is not None and liability["status"] != status:
            continue
        rows.append(liability)
    return collection_response(rows, limit, offset)


@bp.get("/nqdc-liabilities/<liability_id>")
def read_liability(liability_id):
    authorize(READ_ROLES)
    return resource_response(find_liability(liability_id))


@bp.post("/nqdc-liabilities/<liability_id>/settle")
def settle_liability(liability_id):
    authorize(("TreasuryController",))
    liability = find_liability(liability_id)
    guard_terminal(liability["status"], ("SETTLED",))
    guard_transition(liability["status"] == "ACTIVE")
    liability["status"] = "SETTLED"
    touch(liability)
    plan = db.nqdc_plans.get(liability["nqdc_plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    recompute_plan(plan, freeze_if_critical=False)
    return resource_response(liability)
