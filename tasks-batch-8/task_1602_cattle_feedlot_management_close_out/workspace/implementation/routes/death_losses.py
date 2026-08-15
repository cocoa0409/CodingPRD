"""Death loss endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_LOT_NOT_FOUND, ERR_DEATH_LOSS_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import death_loss_out, insurance_claim_out
from services import health_service
from util import body_json, get_or_404, list_response, req_str, req_int, \
    req_date, req_bool, success_object

bp = Blueprint("death_losses", __name__)


@bp.route("/feedlot/death-losses", methods=["POST"])
def create_death_loss():
    _, role = authenticate()
    authorize(role, ["CattleHealthTech"])
    body = body_json()

    lot_id = req_str(body, "lot_id")
    loss_date = req_date(body, "loss_date")
    head_count = req_int(body, "head_count")
    cause = req_str(body, "cause")
    insured = req_bool(body, "insured")

    # Validate lot exists
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)

    rec = health_service.create_death_loss(lot, loss_date, head_count, cause, insured)
    return success_object(death_loss_out(rec), 201)


@bp.route("/feedlot/death-losses/<death_loss_id>", methods=["GET"])
def get_death_loss(death_loss_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.death_losses, death_loss_id, ERR_DEATH_LOSS_NOT_FOUND, "DeathLoss")
    return success_object(death_loss_out(rec))


@bp.route("/feedlot/death-losses/<death_loss_id>/void", methods=["POST"])
def void_death_loss(death_loss_id):
    _, role = authenticate()
    authorize(role, ["CattleHealthTech"])
    rec = get_or_404(store.death_losses, death_loss_id, ERR_DEATH_LOSS_NOT_FOUND, "DeathLoss")
    health_service.void_death_loss(rec)
    return success_object(death_loss_out(rec))


@bp.route("/feedlot/death-losses/<death_loss_id>/insurance-claims", methods=["GET"])
def list_death_loss_claims(death_loss_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.death_losses, death_loss_id, ERR_DEATH_LOSS_NOT_FOUND, "DeathLoss")
    claims = [c for c in store.insurance_claims.values() if c["death_loss_id"] == death_loss_id]
    return list_response(claims, insurance_claim_out)
