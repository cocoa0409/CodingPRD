"""Payout endpoints (PRD §3.8)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, payout_ops
from services.store_helpers import make_record, get_claim, get_payout

bp = Blueprint("payouts", __name__)


@bp.route("/payouts", methods=["POST"])
@require_roles("ClaimsAdjuster")
def create_payout():
    body = common.get_json_body()
    claim_id = common.require_str(body, "claim_id")

    claim = get_claim(claim_id)

    if claim["status"] != "APPROVED":
        raise errors.conflict(errors.ERR_CLAIM_NOT_APPROVED, "Claim is not APPROVED.")

    rec = make_record()
    rec.update({
        "claim_id": claim_id,
        "policy_id": claim["policy_id"],
        "amount_cents": claim["approved_amount_cents"],
        "status": "PENDING",
    })
    db.payouts[rec["id"]] = rec
    return response.success_object(serialize.payout_out(rec), status=201)


@bp.route("/payouts/<payout_id>", methods=["GET"])
@require_roles("Any")
def get_payout_route(payout_id):
    rec = get_payout(payout_id)
    return response.success_object(serialize.payout_out(rec), status=200)


@bp.route("/payouts", methods=["GET"])
@require_roles("Any")
def list_payouts():
    items = list(db.payouts.values())
    for field in ("claim_id", "policy_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.payout_out(p) for p in page], limit, offset, total)


@bp.route("/payouts/<payout_id>/disburse", methods=["POST"])
@require_roles("ClaimsAdjuster")
def disburse(payout_id):
    rec = get_payout(payout_id)
    payout_ops.disburse(rec)
    return response.success_object(serialize.payout_out(rec), status=200)


@bp.route("/payouts/<payout_id>/reverse", methods=["POST"])
@require_roles("ClaimsAdjuster")
def reverse(payout_id):
    rec = get_payout(payout_id)
    payout_ops.reverse(rec)
    return response.success_object(serialize.payout_out(rec), status=200)
