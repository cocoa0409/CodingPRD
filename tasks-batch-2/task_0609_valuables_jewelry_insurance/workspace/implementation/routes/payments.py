"""PremiumPayment routes: record/get/list, reverse."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
import db
import lookups
import response
import serializers
import validators as V
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_policy_access

bp = Blueprint("payments", __name__)


@bp.route("/policies/<pid>/payments", methods=["POST"])
def record_payment(pid):
    user_id, role = get_identity()
    require_role(role, {"Policyholder", "Underwriter"})
    policy = lookups.get_policy(pid)
    assert_policy_access(policy, user_id, role)

    body = V.get_json(request)
    amount = V.require_positive_int(body, "amount_cents")

    # Billable only after bind (priority 18).
    if policy["coverage_status"] not in ("BOUND", "ACTIVE", "LAPSED"):
        raise err("ERR_POLICY_NOT_BILLABLE", "Policy is not billable")

    # Sufficient amount (priority 17).
    if amount < (policy["annual_premium_cents"] or 0):
        raise err("ERR_PREMIUM_UNDERPAID", "Payment below annual premium")

    rec = {
        "id": db.new_id(),
        "policy_id": policy["id"],
        "amount_cents": amount,
        "status": "RECEIVED",
    }
    db.stamp_create(rec)
    db.premium_payments[rec["id"]] = rec

    prior_coverage = policy["coverage_status"]
    policy["billing_status"] = "PAID"

    # Coverage bubble.
    if prior_coverage == "BOUND":
        policy["coverage_status"] = "ACTIVE"
    elif prior_coverage == "LAPSED":
        anchor = clock.parse_iso(policy.get("past_due_since"))
        now = clock.now()
        if anchor is not None and now <= anchor + timedelta(days=calc.REINSTATE_DAYS):
            policy["coverage_status"] = "ACTIVE"

    policy["past_due_since"] = None
    db.touch(policy)
    return response.success(serializers.premium_payment(rec), status=201)


@bp.route("/premium-payments/<ppid>", methods=["GET"])
def get_payment(ppid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_premium_payment(ppid)
    policy = db.policies.get(rec["policy_id"])
    if policy is not None:
        assert_policy_access(policy, user_id, role)
    return response.success(serializers.premium_payment(rec), status=200)


@bp.route("/premium-payments", methods=["GET"])
def list_payments():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    policy_id = request.args.get("policy_id")
    records = list(db.premium_payments.values())
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if role == "Policyholder":
        owned = {p["id"] for p in db.policies.values() if p["policyholder_id"] == user_id}
        records = [r for r in records if r["policy_id"] in owned]
    return paginate_and_respond(records, serializers.premium_payment)


@bp.route("/policies/<pid>/payments/<ppid>/reverse", methods=["POST"])
def reverse_payment(pid, ppid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)
    payment = lookups.get_premium_payment(ppid)
    if payment["policy_id"] != policy["id"]:
        raise err("ERR_NOT_FOUND", "Payment does not belong to this policy")

    if payment["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "Payment is not RECEIVED")

    payment["status"] = "REVERSED"
    db.touch(payment)
    policy["billing_status"] = "PAST_DUE"
    policy["past_due_since"] = clock.now_iso()
    db.touch(policy)
    return response.success(serializers.premium_payment(payment), status=200)
