"""Insurance claim endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_DEATH_LOSS_NOT_FOUND, ERR_INSURANCE_CLAIM_NOT_FOUND, \
    ERR_INVALID_REQUEST, raise_err
from serializers import insurance_claim_out
from services import claim_service
from util import body_json, get_or_404, req_str, req_int, opt_int, success_object

bp = Blueprint("insurance_claims", __name__)


@bp.route("/feedlot/insurance-claims", methods=["POST"])
def create_claim():
    _, role = authenticate()
    authorize(role, ["CattleHealthTech"])
    body = body_json()

    death_loss_id = req_str(body, "death_loss_id")
    claimed_amount_cents = req_int(body, "claimed_amount_cents")

    death_loss = store.death_losses.get(death_loss_id)
    if death_loss is None:
        raise_err(ERR_DEATH_LOSS_NOT_FOUND, "Death loss not found: %s" % death_loss_id)

    rec = claim_service.create_claim(death_loss, claimed_amount_cents)
    return success_object(insurance_claim_out(rec), 201)


@bp.route("/feedlot/insurance-claims/<claim_id>/decide", methods=["POST"])
def decide_claim(claim_id):
    uid, role = authenticate()
    authorize(role, ["ClaimsAdjuster"])
    body = body_json()

    decision = req_str(body, "decision")
    approved_amount_cents = opt_int(body, "approved_amount_cents")

    if decision not in ("APPROVE", "DENY"):
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")

    rec = get_or_404(store.insurance_claims, claim_id,
                     ERR_INSURANCE_CLAIM_NOT_FOUND, "InsuranceClaim")

    claim_service.decide_claim(rec, decision, approved_amount_cents, uid)
    return success_object(insurance_claim_out(rec))


@bp.route("/feedlot/insurance-claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    _, role = authenticate()
    authorize(role, ["ClaimsAdjuster"])

    rec = get_or_404(store.insurance_claims, claim_id,
                     ERR_INSURANCE_CLAIM_NOT_FOUND, "InsuranceClaim")

    claim_service.appeal_claim(rec)
    return success_object(insurance_claim_out(rec))


@bp.route("/feedlot/insurance-claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    uid, role = authenticate()
    authorize(role, ["ClaimsTreasurer", "ClaimsAdjuster"])

    rec = get_or_404(store.insurance_claims, claim_id,
                     ERR_INSURANCE_CLAIM_NOT_FOUND, "InsuranceClaim")

    claim_service.pay_claim(rec, uid)
    return success_object(insurance_claim_out(rec))
