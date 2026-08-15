"""Health event endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_LOT_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import health_event_out
from services import health_service
from util import body_json, get_or_404, req_str, req_int, req_date, success_object

bp = Blueprint("health_events", __name__)


@bp.route("/feedlot/health-events", methods=["POST"])
def create_health_event():
    _, role = authenticate()
    authorize(role, ["CattleHealthTech"])
    body = body_json()

    lot_id = req_str(body, "lot_id")
    treatment_date = req_date(body, "treatment_date")
    drug_product = req_str(body, "drug_product")
    withdrawal_days = req_int(body, "withdrawal_days")
    head_treated = req_int(body, "head_treated")
    treatment_cost_cents = req_int(body, "treatment_cost_cents")

    # Validate ranges
    if withdrawal_days < 0:
        raise_err(ERR_INVALID_REQUEST, "withdrawal_days must be >= 0")
    if treatment_cost_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "treatment_cost_cents must be >= 0")

    # Validate lot exists
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)

    rec = health_service.create_health_event(
        lot, treatment_date, drug_product, withdrawal_days,
        head_treated, treatment_cost_cents
    )
    return success_object(health_event_out(rec), 201)
