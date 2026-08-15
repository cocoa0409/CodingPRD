"""Escrow deposit endpoints (PRD 3.7). Funding bubbles the transaction
OPENED -> ESCROW_FUNDED in the same request."""
from flask import Blueprint

import db as dbmod
from errors import (
    ERR_ESCROW_DEPOSIT_NOT_FOUND,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, serialize, touch
from validate import body, req_str

bp = Blueprint("escrow", __name__)


def _get_escrow(escrow_id):
    rec = dbmod.db["escrows"].get(escrow_id)
    if rec is None:
        raise_error(ERR_ESCROW_DEPOSIT_NOT_FOUND,
                    "escrow deposit id does not exist")
    return rec


@bp.get("/api/escrow-deposits")
@require_roles(ALL_ROLES)
def list_escrows():
    return list_page("escrows", ["transaction_id"])


@bp.get("/api/escrow-deposits/<escrow_id>")
@require_roles(ALL_ROLES)
def get_escrow(escrow_id):
    return success_object(serialize("escrows", _get_escrow(escrow_id)))


@bp.post("/api/escrow-deposits/<escrow_id>/fund")
@require_roles(["EscrowOfficer"])
def fund_escrow(escrow_id):
    esc = _get_escrow(escrow_id)
    b = body()
    reference = req_str(b, "funding_reference")
    if esc["status"] != "AWAITING_FUNDS":
        raise_error(
            ERR_INVALID_STATE,
            "only an AWAITING_FUNDS escrow deposit can be funded",
        )
    esc["status"] = "FUNDED"
    esc["funding_reference"] = reference
    touch(esc)
    # Bubble up: the funding event arms the deal for inspection.
    tx = dbmod.db["transactions"].get(esc["transaction_id"])
    if tx is not None and tx["status"] == "OPENED":
        tx["status"] = "ESCROW_FUNDED"
        touch(tx)
    return success_object(serialize("escrows", esc))
