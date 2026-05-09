"""Contract + Signature routes."""
import copy

from flask import Blueprint

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, stamp_new, stamp_update
from db import db, new_id
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import append_audit
from services.transitions import (
    evaluate_effective_transition,
    evaluate_signed_transition,
    evaluate_supersede,
)

bp = Blueprint("contracts", __name__)


@bp.route("/contracts", methods=["POST"])
def create_contract():
    user_id, role = require_roles(["RightsHolder"])
    body = get_json_body()

    license_id = body.get("license_id")
    signing_order = body.get("signing_order")
    effective_date_target = body.get("effective_date_target")
    parent_contract_id = body.get("parent_contract_id")

    if not license_id:
        raise api_error("ERR_VALIDATION", "license_id required")
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")

    # Caller must be a participant in the license.
    if user_id not in (license_obj["licensor_id"], license_obj["licensee_id"]):
        raise api_error("ERR_FORBIDDEN", "caller must be licensor or licensee")

    if license_obj.get("status") != "ACCEPTED":
        raise api_error("ERR_LICENSE_NOT_ACCEPTED",
                        "License must be in ACCEPTED to create a contract")

    if not isinstance(signing_order, list) or not signing_order:
        raise api_error("ERR_VALIDATION", "signing_order must be non-empty array")
    for sid in signing_order:
        if sid not in db.rights_holders:
            raise api_error("ERR_NOT_FOUND", f"signer {sid} not found")

    if not effective_date_target:
        raise api_error("ERR_EFFECTIVE_DATE_OUT_OF_TERM", "effective_date_target required")
    edt = parse_iso(effective_date_target)
    ts = parse_iso(license_obj.get("term_start"))
    te = parse_iso(license_obj.get("term_end"))
    if edt is None or ts is None or te is None:
        raise api_error("ERR_EFFECTIVE_DATE_OUT_OF_TERM",
                        "effective_date_target outside [term_start, term_end)")
    if not (ts <= edt < te):
        raise api_error("ERR_EFFECTIVE_DATE_OUT_OF_TERM",
                        "effective_date_target outside [term_start, term_end)")

    parent = None
    if parent_contract_id is not None:
        parent = db.contracts.get(parent_contract_id)
        if not parent:
            raise api_error("ERR_NOT_FOUND", "parent contract not found")
        if parent.get("status") != "EFFECTIVE":
            raise api_error("ERR_INVALID_STATE",
                            "parent contract must be EFFECTIVE to be supplemented")

    contract = {
        "license_id": license_id,
        "signing_order": list(signing_order),
        "effective_date_target": effective_date_target,
        "status": "PENDING_SIGNATURES",
        "signed_count": 0,
        "fully_signed_at": None,
        "parent_contract_id": parent_contract_id,
    }
    stamp_new(contract)
    db.contracts[contract["id"]] = contract

    # Link license.contract_id only for primary contracts; supplementary contracts
    # do not displace the primary's link until they reach FULLY_SIGNED (supersede).
    if parent_contract_id is None:
        license_obj["contract_id"] = contract["id"]
        stamp_update(license_obj)

    append_audit(user_id, "Contract", contract["id"], "CONTRACT_AMENDED",
                 None, {"status": contract["status"], "license_id": license_id})

    return success(contract, status=201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    contract = db.contracts.get(contract_id)
    if not contract:
        raise api_error("ERR_NOT_FOUND", "contract not found")
    return success(contract)


@bp.route("/contracts/<contract_id>/signatures", methods=["POST"])
def submit_signature(contract_id):
    user_id, role = require_roles(["RightsHolder"])
    contract = db.contracts.get(contract_id)
    if not contract:
        raise api_error("ERR_NOT_FOUND", "contract not found")
    body = get_json_body()
    check_version(contract, body)

    if contract.get("status") != "PENDING_SIGNATURES":
        raise api_error("ERR_INVALID_STATE", "contract not pending signatures")

    license_obj = db.licenses.get(contract.get("license_id"))
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    if license_obj.get("status") != "ACCEPTED":
        raise api_error("ERR_LICENSE_NOT_ACCEPTED",
                        "underlying license must be ACCEPTED")

    signer_id = body.get("signer_id")
    payload = body.get("signature_payload")
    if not signer_id or signer_id not in db.rights_holders:
        raise api_error("ERR_NOT_FOUND", "signer not found")
    if not payload:
        raise api_error("ERR_VALIDATION", "signature_payload required")

    # Caller must equal signer.
    if user_id != signer_id:
        raise api_error("ERR_FORBIDDEN", "caller must equal signer_id")

    # Order check (priority 10).
    expected = contract["signing_order"][contract["signed_count"]]
    if signer_id != expected:
        raise api_error("ERR_SIGNATURE_OUT_OF_ORDER",
                        f"expected signer {expected}, got {signer_id}")

    # Duplicate (priority 11).
    for s in db.signatures.values():
        if s.get("contract_id") == contract_id and s.get("signer_id") == signer_id:
            raise api_error("ERR_DUPLICATE_SIGNATURE",
                            "this signer has already signed the contract")

    sig = {
        "id": new_id(),
        "created_at": format_iso(get_now()),
        "contract_id": contract_id,
        "signer_id": signer_id,
        "signature_payload": payload,
        "signed_at": format_iso(get_now()),
    }
    db.signatures[sig["id"]] = sig
    contract["signed_count"] += 1
    stamp_update(contract)

    # Auto-transition: FULLY_SIGNED when signed_count == len(signing_order)
    if contract["signed_count"] == len(contract["signing_order"]):
        before = {"status": contract["status"]}
        contract["status"] = "FULLY_SIGNED"
        contract["fully_signed_at"] = format_iso(get_now())
        stamp_update(contract)
        append_audit("system", "Contract", contract["id"], "CONTRACT_AMENDED",
                     before, {"status": "FULLY_SIGNED"})

        # Cascade: License ACCEPTED → SIGNED (only for primary contract).
        if contract.get("parent_contract_id") is None:
            evaluate_signed_transition(contract)
            # If the effective_date_target is already in the past or now, advance.
            evaluate_effective_transition(contract)
        else:
            # Supplementary: parent EFFECTIVE → SUPERSEDED
            evaluate_supersede(contract)

    return success(sig, status=201)
