"""Plan, Actuary, and logical-clock endpoints."""

from flask import Blueprint, request

from db import store, parse_iso, fmt_ts
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import invalid_state, validation, ERR_INVALID_STATE, ApiError
from validate import body_of, req_str, req_int, req_num, opt_num, has_field
from services.core import (
    base_record, touch, public, get_plan, get_actuary, serialize_plan,
    evaluate_delinquency, r2,
)
from decimal import Decimal

bp = Blueprint("plans", __name__)

ALL_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor", "FirmAdmin"]


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

@bp.route("/v1/plans", methods=["POST"])
def create_plan():
    require_roles(["PlanAdmin"])
    body = body_of(request)

    sponsor_name = req_str(body, "sponsor_name")
    plan_year = req_int(body, "plan_year")
    accrual_rate = req_num(body, "accrual_rate")
    if not (Decimal(0) < Decimal(str(accrual_rate)) <= Decimal("0.10")):
        raise validation("accrual_rate must be in (0, 0.10]")
    normal_retirement_age = req_int(body, "normal_retirement_age")
    if not (60 <= normal_retirement_age <= 63):
        raise validation("normal_retirement_age must be in [60, 63]")
    prior_aftap_pct = req_num(body, "prior_aftap_pct")
    if not (Decimal(0) <= Decimal(str(prior_aftap_pct)) <= Decimal("200")):
        raise validation("prior_aftap_pct must be in [0.00, 200.00]")
    initial_carryover = opt_num(body, "initial_carryover_balance", 0)
    initial_prefunding = opt_num(body, "initial_prefunding_balance", 0)

    rec = base_record()
    rec.update({
        "sponsor_name": sponsor_name,
        "plan_year": plan_year,
        "accrual_rate": accrual_rate,
        "normal_retirement_age": normal_retirement_age,
        "prior_aftap_pct": r2(prior_aftap_pct),
        "status": "ACTIVE",
        "current_posture": "UNRESTRICTED",
        "certified_aftap_pct": None,
    })
    store.plans[rec["id"]] = rec

    # side effect: auto-create the 1:1 credit-balance ledger
    ledger = base_record()
    ledger.update({
        "plan_id": rec["id"],
        "carryover_balance": r2(initial_carryover),
        "prefunding_balance": r2(initial_prefunding),
        "total_applied_to_date": 0.0,
    })
    store.credit_balance_ledgers[rec["id"]] = ledger

    return success_object(serialize_plan(rec), status=201)


@bp.route("/v1/plans", methods=["GET"])
def list_plans():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "TERMINATED"):
        raise validation("status must be ACTIVE or TERMINATED")
    items = list(store.plans.values())
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, total = list_page(items, limit, offset)
    return success_list([serialize_plan(p) for p in page], limit, offset, total)


@bp.route("/v1/plans/<plan_id>", methods=["GET"])
def fetch_plan(plan_id):
    require_roles(ALL_ROLES)
    plan = get_plan(plan_id)
    return success_object(serialize_plan(plan))


@bp.route("/v1/plans/<plan_id>/terminate", methods=["POST"])
def terminate_plan(plan_id):
    require_roles(["PlanAdmin"])
    plan = get_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise invalid_state("Plan is not ACTIVE")
    # precondition: no contribution demand with outstanding_amount > 0
    for d in store.contribution_demands.values():
        if d["plan_id"] == plan["id"] and d["outstanding_amount"] > 0:
            raise ApiError(ERR_INVALID_STATE, 409, "Contribution demand remains outstanding")
    plan["status"] = "TERMINATED"
    touch(plan)
    # side effect: every DRAFT PBGC filing of the plan -> VOID
    for f in store.pbgc_filings.values():
        if f["plan_id"] == plan["id"] and f["status"] == "DRAFT":
            f["status"] = "VOID"
            touch(f)
    return success_object(serialize_plan(plan))


# ---------------------------------------------------------------------------
# Actuary registry
# ---------------------------------------------------------------------------

@bp.route("/v1/actuaries", methods=["POST"])
def create_actuary():
    require_roles(["FirmAdmin"])
    body = body_of(request)
    full_name = req_str(body, "full_name")
    credential_id = req_str(body, "credential_id")
    enrollment_status = req_str(body, "enrollment_status")
    if enrollment_status not in ("ENROLLED", "ASSOCIATE"):
        raise validation("enrollment_status must be ENROLLED or ASSOCIATE")
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "credential_id": credential_id,
        "enrollment_status": enrollment_status,
    })
    store.actuaries[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/actuaries/<actuary_id>", methods=["GET"])
def fetch_actuary(actuary_id):
    require_roles(ALL_ROLES)
    rec = get_actuary(actuary_id)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["FirmAdmin"])
    body = body_of(request)
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso8601)
    except Exception:
        raise validation("to_iso8601 must be an ISO 8601 datetime")
    store.clock.set(dt)
    # side effect: re-evaluate contribution-demand delinquency
    evaluate_delinquency()
    return success_object({"current_utc": fmt_ts(store.clock.now())})
