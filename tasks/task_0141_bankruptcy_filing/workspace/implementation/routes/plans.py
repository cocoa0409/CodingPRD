"""Plan and TrusteePayment endpoints."""

from flask import Blueprint, g

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import (
    confirm_plan,
    create_plan,
    get_case_or_404,
    get_plan_scoped_or_404,
    record_trustee_payment,
    withdraw_plan,
    check_occ,
)
from services.serializers import serialize_plan, serialize_trustee_payment
from db import store


plans_bp = Blueprint("plans", __name__)


@plans_bp.post("/cases/<case_id>/plans")
@require_auth(allowed_roles=["Debtor"])
def create_plan_route(case_id: str):
    body = parse_json_body(required_fields=["proposed_monthly_payment_cents", "plan_months"])
    with store.lock:
        case = get_case_or_404(case_id)
        plan = create_plan(
            case,
            proposed_monthly_payment_cents=body["proposed_monthly_payment_cents"],
            plan_months=body["plan_months"],
            acting_user_id=g.user_id,
        )
    return success(serialize_plan(plan), status=201)


@plans_bp.get("/cases/<case_id>/plans/<plan_id>")
@require_auth(allowed_roles=["Debtor", "Trustee", "Judge"])
def get_plan_route(case_id: str, plan_id: str):
    plan = get_plan_scoped_or_404(case_id, plan_id)
    return success(serialize_plan(plan))


@plans_bp.delete("/cases/<case_id>/plans/<plan_id>")
@require_auth(allowed_roles=["Debtor"])
def withdraw_plan_route(case_id: str, plan_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        plan = get_plan_scoped_or_404(case_id, plan_id)
        check_occ(plan, body.get("version"))
        plan = withdraw_plan(case, plan, acting_user_id=g.user_id)
    return success(serialize_plan(plan))


@plans_bp.post("/cases/<case_id>/plans/<plan_id>/confirm")
@require_auth(allowed_roles=["Judge"])
def confirm_plan_route(case_id: str, plan_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        plan = get_plan_scoped_or_404(case_id, plan_id)
        check_occ(plan, body.get("version"))
        plan = confirm_plan(case, plan)
    return success(serialize_plan(plan))


@plans_bp.post("/cases/<case_id>/plans/<plan_id>/payments")
@require_auth(allowed_roles=["Debtor", "Trustee"])
def record_payment_route(case_id: str, plan_id: str):
    body = parse_json_body(required_fields=["sequence_number", "amount_cents", "status"])
    with store.lock:
        case = get_case_or_404(case_id)
        plan = get_plan_scoped_or_404(case_id, plan_id)
        payment = record_trustee_payment(
            case,
            plan,
            sequence_number=body["sequence_number"],
            amount_cents=body["amount_cents"],
            status=body["status"],
        )
    return success(serialize_trustee_payment(payment), status=201)
