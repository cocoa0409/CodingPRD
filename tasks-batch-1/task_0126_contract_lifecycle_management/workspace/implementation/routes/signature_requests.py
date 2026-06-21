"""SignatureRequest sign/decline endpoints (PRD §3.5)."""

from flask import Blueprint

from common import bump, serialize
from db import db
from errors import invalid_state, resource_not_found
from middleware import require_roles
from response import success_object
from services.contract_logic import activate_contract, decline_cascade
from util import format_iso_millis

bp = Blueprint("signature_requests", __name__)


@bp.route("/signature-requests/<sid>/sign", methods=["POST"])
@require_roles("Signer")
def sign(sid):
    sr = db.signature_requests.get(sid)
    if not sr:
        raise resource_not_found("Signature request not found.")

    contract = db.contracts.get(sr.get("contract_id"))

    # Sign is only valid while parent contract is OUT_FOR_SIGNATURE and the
    # request is SENT (PRD §3.5; else ERR_INVALID_STATE).
    if sr.get("status") != "SENT" or (contract and contract.get("status") != "OUT_FOR_SIGNATURE"):
        raise invalid_state("Signature request is not signable in this state.")

    sr["signed_at"] = format_iso_millis(db.clock)
    sr["status"] = "SIGNED"
    bump(sr)

    # JOIN: if all sibling requests are now SIGNED, activate the contract.
    siblings = [s for s in db.signature_requests.values()
                if s.get("contract_id") == contract.get("id")]
    if siblings and all(s.get("status") == "SIGNED" for s in siblings):
        activate_contract(contract)

    return success_object(serialize(sr), status=200)


@bp.route("/signature-requests/<sid>/decline", methods=["POST"])
@require_roles("Signer")
def decline(sid):
    sr = db.signature_requests.get(sid)
    if not sr:
        raise resource_not_found("Signature request not found.")

    contract = db.contracts.get(sr.get("contract_id"))

    if sr.get("status") != "SENT" or (contract and contract.get("status") != "OUT_FOR_SIGNATURE"):
        raise invalid_state("Signature request is not declinable in this state.")

    sr["status"] = "DECLINED"
    bump(sr)

    # Bubble up: contract -> REDLINING; sibling SENT requests -> VOIDED.
    decline_cascade(sr, contract)

    return success_object(serialize(sr), status=200)
