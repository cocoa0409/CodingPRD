"""FundsTransfer endpoints — mark_received / mark_failed with cascades."""
from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import require_roles
from response import success_object
from routes.common import lookup_or_404
from services.serializers import transfer_view

bp = Blueprint("transfers", __name__)


def _now():
    return db.now_formatted()


def _bump(entity, now):
    entity["version"] += 1
    entity["updated_at"] = now


@bp.route("/transfers/<tid>/mark_received", methods=["POST"])
def mark_received(tid):
    require_roles("OperationsDesk")
    transfer = lookup_or_404(db.transfers, tid, "FundsTransfer")
    case = db.cases.get(transfer["case_id"])
    if case is None:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Parent case not found", 409)
    # Precondition: case's FundsTransfer.status == REQUESTED
    if transfer["status"] != "REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Transfer must be REQUESTED to mark received",
            409,
        )
    now = _now()
    transfer["status"] = "RECEIVED"
    transfer["received_at"] = now
    _bump(transfer, now)

    # Cascade: case FUNDS_REQUESTED -> FUNDS_RECEIVED
    if case["status"] != "FUNDS_REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be FUNDS_REQUESTED when transfer is marked received",
            409,
        )
    case["status"] = "FUNDS_RECEIVED"
    _bump(case, now)

    # Cascade: contract SURRENDER_PENDING -> EXCHANGED with value/basis reduction
    contract = db.contracts[case["existing_contract_id"]]
    contract["status"] = "EXCHANGED"
    if case["exchange_type"] == "FULL":
        contract["account_value_cents"] = 0
        contract["tax_basis_cents"] = 0
    else:
        contract["account_value_cents"] -= case["exchange_amount_cents"]
        contract["tax_basis_cents"] -= transfer["basis_transferred_cents"]
    _bump(contract, now)

    return success_object(transfer_view(transfer), 200)


@bp.route("/transfers/<tid>/mark_failed", methods=["POST"])
def mark_failed(tid):
    require_roles("OperationsDesk")
    transfer = lookup_or_404(db.transfers, tid, "FundsTransfer")
    case = db.cases.get(transfer["case_id"])
    if case is None:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Parent case not found", 409)
    if transfer["status"] != "REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Transfer must be REQUESTED to mark failed",
            409,
        )
    now = _now()
    transfer["status"] = "FAILED"
    _bump(transfer, now)

    # Compensating cascade: case FUNDS_REQUESTED -> APPROVED
    if case["status"] != "FUNDS_REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be FUNDS_REQUESTED when transfer is marked failed",
            409,
        )
    case["status"] = "APPROVED"
    _bump(case, now)

    # Compensating cascade: contract SURRENDER_PENDING -> IN_FORCE
    contract = db.contracts[case["existing_contract_id"]]
    contract["status"] = "IN_FORCE"
    _bump(contract, now)

    return success_object(transfer_view(transfer), 200)
