"""Deductible reimbursement endpoints (§3.7)."""
from flask import Blueprint, request

import errors
import serialize
from auth import authorize
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, touch, clock_now

bp = Blueprint("reimbursements", __name__)


@bp.route("/subro/deductible-reimbursements/<deductible_reimbursement_id>", methods=["GET"])
def get_reimbursement(deductible_reimbursement_id):
    authorize(request, None)
    reimb = lookup_or_404(db.deductible_reimbursements, deductible_reimbursement_id)
    return success(serialize.deductible_reimbursement(reimb), "object", 200)


@bp.route("/subro/deductible-reimbursements", methods=["GET"])
def list_reimbursements():
    authorize(request, None)
    claim_id = request.args.get("claim_id")
    recovery_payment_id = request.args.get("recovery_payment_id")
    status = request.args.get("status")
    items = []
    for r in db.deductible_reimbursements.values():
        if claim_id is not None and r["claim_id"] != claim_id:
            continue
        if recovery_payment_id is not None and r["recovery_payment_id"] != recovery_payment_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    return respond_list(request, items, serialize.deductible_reimbursement)


@bp.route("/subro/deductible-reimbursements/<deductible_reimbursement_id>/disburse", methods=["POST"])
def disburse(deductible_reimbursement_id):
    authorize(request, {"FinanceOfficer"})
    reimb = lookup_or_404(db.deductible_reimbursements, deductible_reimbursement_id)
    # (7) state
    if reimb["status"] != "PENDING":
        raise errors.invalid_state()
    # funding payment must still be CLEARED
    payment = db.recovery_payments[reimb["recovery_payment_id"]]
    if payment["status"] != "CLEARED":
        raise errors.invalid_state("Funding recovery payment is not CLEARED")

    reimb["status"] = "DISBURSED"
    reimb["disbursed_at"] = clock_now()
    touch(reimb)
    claim = db.claims[reimb["claim_id"]]
    claim["deductible_reimbursed_cents"] += reimb["amount_cents"]
    touch(claim)
    return success(serialize.deductible_reimbursement(reimb), "object", 200)
