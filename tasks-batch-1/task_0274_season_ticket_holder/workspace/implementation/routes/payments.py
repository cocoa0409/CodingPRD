"""PaymentPlan and Installment: create, pay, default, fetch, list."""
from flask import Blueprint, request

import db
import calculations as calc
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    installment_view,
    paginate,
    payment_plan_view,
    require_int,
    require_str,
)
from middleware import get_auth, require_role
from response import success, success_list

bp = Blueprint("payments", __name__)


@bp.route("/payment-plans", methods=["POST"])
def create_payment_plan():
    _, role = get_auth()
    require_role(role, {"FinanceClerk"})
    body = get_json_body()
    subscription_id = require_str(body, "subscription_id")
    with db.lock:
        sub = db.subscriptions.get(subscription_id)
        if sub is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "subscription_id not found")
        installment_count = require_int(body, "installment_count", minimum=2, maximum=12)

        # At most one ACTIVE plan per subscription.
        for p in db.payment_plans.values():
            if p["subscription_id"] == subscription_id and p["status"] == "ACTIVE":
                raise err("ERR_PAYMENT_PLAN_EXISTS", "An ACTIVE payment plan already exists")

        total = sub["locked_price_cents"]
        plan = db.new_common()
        plan.update(
            {
                "subscription_id": subscription_id,
                "total_cents": total,
                "installment_count": installment_count,
                "amount_paid_cents": 0,
                "status": "ACTIVE",
            }
        )
        db.payment_plans[plan["id"]] = plan

        amounts = calc.installment_allocation(total, installment_count)
        for seq, amount in enumerate(amounts, start=1):
            inst = db.new_common()
            inst.update(
                {
                    "payment_plan_id": plan["id"],
                    "sequence": seq,
                    "amount_cents": amount,
                    "status": "SCHEDULED",
                }
            )
            db.installments[inst["id"]] = inst

        return success(payment_plan_view(plan), 201)


@bp.route("/payment-plans/<rid>", methods=["GET"])
def get_payment_plan(rid):
    _, role = get_auth()
    require_role(role, {"FinanceClerk", "AccountHolder", "BoxOfficeAgent"})
    with db.lock:
        row = get_or_404(db.payment_plans, rid)
        return success(payment_plan_view(row))


@bp.route("/payment-plans", methods=["GET"])
def list_payment_plans():
    _, role = get_auth()
    require_role(role, {"FinanceClerk", "BoxOfficeAgent"})
    subscription_id = request.args.get("subscription_id")
    status = request.args.get("status")
    with db.lock:
        rows = [
            p
            for p in db.payment_plans.values()
            if (subscription_id is None or p["subscription_id"] == subscription_id)
            and (status is None or p["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([payment_plan_view(r) for r in page], limit, offset, total)


@bp.route("/payment-plans/<rid>/installments", methods=["GET"])
def list_plan_installments(rid):
    _, role = get_auth()
    require_role(role, {"FinanceClerk", "AccountHolder", "BoxOfficeAgent"})
    status = request.args.get("status")
    with db.lock:
        get_or_404(db.payment_plans, rid)
        rows = [
            i
            for i in db.installments.values()
            if i["payment_plan_id"] == rid and (status is None or i["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([installment_view(r) for r in page], limit, offset, total)


@bp.route("/installments/<rid>", methods=["GET"])
def get_installment(rid):
    _, role = get_auth()
    require_role(role, {"FinanceClerk", "AccountHolder", "BoxOfficeAgent"})
    with db.lock:
        row = get_or_404(db.installments, rid)
        return success(installment_view(row))


@bp.route("/payment-plans/<rid>/installments/<seq>/pay", methods=["POST"])
def pay_installment(rid, seq):
    _, role = get_auth()
    require_role(role, {"FinanceClerk"})
    with db.lock:
        plan = get_or_404(db.payment_plans, rid)
        # Resolve the installment by sequence within this plan.
        try:
            seq_num = int(seq)
        except (ValueError, TypeError):
            raise err("ERR_NOT_FOUND", "Installment not found")
        target = None
        for i in db.installments.values():
            if i["payment_plan_id"] == rid and i["sequence"] == seq_num:
                target = i
                break
        if target is None:
            raise err("ERR_NOT_FOUND", "Installment not found")

        # State: plan ACTIVE & installment SCHEDULED.
        if plan["status"] != "ACTIVE":
            if plan["status"] in ("PAID_IN_FULL", "DEFAULTED", "CANCELLED"):
                raise err("ERR_VALIDATION_FROM_TERMINAL", "Plan is in terminal state")
            raise err("ERR_INVALID_STATE", "Plan is not ACTIVE")
        if target["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Installment is not SCHEDULED")

        target["status"] = "PAID"
        db.touch(target)
        plan["amount_paid_cents"] += target["amount_cents"]

        # Plan closes when no SCHEDULED installments remain.
        remaining = [
            i
            for i in db.installments.values()
            if i["payment_plan_id"] == rid and i["status"] == "SCHEDULED"
        ]
        if not remaining:
            plan["status"] = "PAID_IN_FULL"
        db.touch(plan)
        return success(installment_view(target))


@bp.route("/payment-plans/<rid>/default", methods=["POST"])
def default_plan(rid):
    _, role = get_auth()
    require_role(role, {"FinanceClerk"})
    with db.lock:
        plan = get_or_404(db.payment_plans, rid)
        if plan["status"] != "ACTIVE":
            if plan["status"] in ("PAID_IN_FULL", "DEFAULTED", "CANCELLED"):
                raise err("ERR_VALIDATION_FROM_TERMINAL", "Plan is in terminal state")
            raise err("ERR_INVALID_STATE", "Plan is not ACTIVE")
        scheduled = [
            i
            for i in db.installments.values()
            if i["payment_plan_id"] == rid and i["status"] == "SCHEDULED"
        ]
        if not scheduled:
            raise err("ERR_INVALID_STATE", "No SCHEDULED installment remains")

        plan["status"] = "DEFAULTED"
        db.touch(plan)

        # Cascade: financed subscription ACTIVE -> SUSPENDED.
        sub = db.subscriptions.get(plan["subscription_id"])
        if sub is not None and sub["status"] == "ACTIVE":
            sub["status"] = "SUSPENDED"
            db.touch(sub)

        return success(payment_plan_view(plan))
