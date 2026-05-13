"""System endpoints: clock, sweep, payment-settled, esign-completed, health."""
from flask import Blueprint, request, g

import db
from errors import APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_BAD_REQUEST
from middleware import require_roles
from response import success
from services import annual_fee_logic, contract_logic, serializers
from services.common import get_or_404
from utils import get_int, get_str

bp = Blueprint("system", __name__)


@bp.route("/_health", methods=["GET"])
def health():
    return success({"status": "ok"})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("Admin")
def advance_clock():
    body = request.get_json(silent=True) or {}
    seconds = get_int(body, "seconds", required=True)
    with db.lock():
        db.advance_clock(seconds)
    return success({"now": db.now_iso()})


@bp.route("/_sweep/annual-fees", methods=["POST"])
@require_roles("Admin")
def sweep():
    with db.lock():
        result = annual_fee_logic.sweep_annual_fees(g.user_role, g.user_id)
    return success(result)


@bp.route("/_events/payment-settled", methods=["POST"])
@require_roles("Admin")
def payment_settled():
    body = request.get_json(silent=True) or {}
    annual_fee_id = get_str(body, "annual_fee_id")
    idempotency_key = get_str(body, "idempotency_key")

    with db.lock():
        # Idempotency: if we've seen this key, return the prior result.
        if idempotency_key in db.idempotency_payment:
            fee_id = db.idempotency_payment[idempotency_key]
            fee = db.annual_fees.get(fee_id)
            if fee:
                return success(serializers.serialize_annual_fee(fee))

        if annual_fee_id not in db.annual_fees:
            raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "annual_fee_id does not resolve")
        fee = db.annual_fees[annual_fee_id]
        annual_fee_logic.pay_fee(fee, g.user_role, g.user_id, via_external=True)
        db.idempotency_payment[idempotency_key] = fee["id"]
    return success(serializers.serialize_annual_fee(fee))


@bp.route("/_events/esign-completed", methods=["POST"])
@require_roles("Admin")
def esign_completed():
    body = request.get_json(silent=True) or {}
    contract_id = get_str(body, "contract_id")
    party_id = get_str(body, "party_id")
    idempotency_key = get_str(body, "idempotency_key")

    with db.lock():
        if idempotency_key in db.idempotency_esign:
            cid = db.idempotency_esign[idempotency_key]
            contract = db.contracts.get(cid)
            if contract:
                return success(serializers.serialize_contract(contract))

        if contract_id not in db.contracts:
            raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "contract_id does not resolve")
        contract = db.contracts[contract_id]
        contract_logic.sign_contract(contract, party_id, g.user_role, g.user_id)
        db.idempotency_esign[idempotency_key] = contract["id"]
    return success(serializers.serialize_contract(contract))
