"""Premium payment endpoints (PRD 3.6): billing-axis transitions and
delinquency recovery."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_POLICY_NOT_BILLABLE, ERR_OVERPAYMENT,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy
from serializers import premium_payment_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_int,
    parse_pagination, paginate, sort_created,
)

bp = Blueprint("premium_payments", __name__)

LIST_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "ClaimsApprover")

CREATE_FIELDS = {"amount_cents"}


@bp.route("/carriers/<carrierId>/policies/<policyId>/premium-payments",
          methods=["POST"])
@require_roles("Policyholder")
def create_premium_payment(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    amount = require_int(body, "amount_cents")
    if amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be greater than zero")

    if policy["lifecycle_state"] not in ("BOUND", "ACTIVE"):
        raise_err(ERR_POLICY_NOT_BILLABLE,
                  "Premium payments are accepted only when BOUND or ACTIVE")

    outstanding = policy["premium_cents"] - policy["premium_paid_cents"]
    if amount > outstanding:
        raise_err(ERR_OVERPAYMENT,
                  "Payment amount exceeds the outstanding balance")

    now = carrier["current_utc"]
    payment = db.stamp_new({
        "policy_id": policy["id"],
        "amount_cents": amount,
        "posted_at": now,
    }, now)
    db.premium_payments[payment["id"]] = payment

    was_delinquent = policy["billing_state"] == "DELINQUENT"
    policy["premium_paid_cents"] += amount
    if policy["premium_paid_cents"] >= policy["premium_cents"]:
        policy["billing_state"] = "PAID_IN_FULL"
    elif policy["billing_state"] == "BILLED":
        policy["billing_state"] = "PARTIALLY_PAID"
    db.touch(policy, now)

    # A cured delinquency reinstates the grower when no other policy of the
    # grower remains delinquent (PRD 3.6).
    if was_delinquent and policy["billing_state"] == "PAID_IN_FULL":
        grower = db.growers.get(policy["grower_id"])
        if grower is not None and grower["status"] == "SUSPENDED":
            still_delinquent = any(
                p["billing_state"] == "DELINQUENT"
                for p in core.policies_of_grower(grower["id"])
            )
            if not still_delinquent:
                grower["status"] = "ACTIVE"
                db.touch(grower, now)

    return success_object(premium_payment_view(payment), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/premium-payments",
          methods=["GET"])
@require_roles(*LIST_ROLES)
def list_premium_payments(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    items = [p for p in db.premium_payments.values() if p["policy_id"] == policy["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([premium_payment_view(p) for p in page], limit, offset, total)
