"""Refund endpoints (PRD §3.5)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, policy_ops
from services.store_helpers import touch, get_refund

bp = Blueprint("refunds", __name__)


@bp.route("/refunds/<refund_id>", methods=["GET"])
@require_roles("Any")
def get_refund_route(refund_id):
    rec = get_refund(refund_id)
    return response.success_object(serialize.refund_out(rec), status=200)


@bp.route("/refunds", methods=["GET"])
@require_roles("Any")
def list_refunds():
    items = list(db.refunds.values())
    for field in ("policy_id", "refund_type", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r[field] == val]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.refund_out(r) for r in page], limit, offset, total)


@bp.route("/refunds/<refund_id>/complete", methods=["POST"])
@require_roles("Underwriter")
def complete_refund(refund_id):
    refund = get_refund(refund_id)
    if refund["status"] != "PENDING":
        raise errors.invalid_state("Refund is not PENDING.")
    policy = db.policies[refund["policy_id"]]
    # Reject if the policy is already REFUNDED by a prior completed refund.
    if policy["payment_status"] == "REFUNDED":
        raise errors.invalid_state("Policy premium is already refunded.")

    refund["status"] = "COMPLETED"
    touch(refund)

    # CASCADE: policy payment_status -> REFUNDED, recompute net premium.
    policy["payment_status"] = "REFUNDED"
    policy_ops.recompute_net_premium(policy)
    touch(policy)

    return response.success_object(serialize.refund_out(refund), status=200)


@bp.route("/refunds/<refund_id>/void", methods=["POST"])
@require_roles("Underwriter")
def void_refund(refund_id):
    refund = get_refund(refund_id)
    if refund["status"] != "PENDING":
        raise errors.invalid_state("Refund is not PENDING.")
    refund["status"] = "VOIDED"
    touch(refund)
    return response.success_object(serialize.refund_out(refund), status=200)
