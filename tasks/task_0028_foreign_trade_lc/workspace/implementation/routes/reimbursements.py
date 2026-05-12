"""Reimbursement claim routes."""

from flask import Blueprint, request, g
import middleware
import response
from services import settlement as svc

bp = Blueprint("reimbursements", __name__)


@bp.route("/reimbursement-claims/<claim_id>", methods=["GET"])
def get(claim_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank", "NegotiatingBank", "Operator", "Auditor")
    return response.success(svc.get_claim(claim_id))


@bp.route("/reimbursement-claims/<claim_id>/honor", methods=["POST"])
def honor(claim_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.honor_claim(claim_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/reimbursement-claims/<claim_id>/dispute", methods=["POST"])
def dispute(claim_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.dispute_claim(claim_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/reimbursement-claims/<claim_id>/extinguish", methods=["POST"])
def extinguish(claim_id):
    middleware.require_auth()
    middleware.require_role("NegotiatingBank")
    return response.success(svc.extinguish_claim(claim_id, request.get_json(silent=True) or {}, g.user_id))
