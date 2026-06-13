from flask import Blueprint, request, g

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup, calc

bp = Blueprint("contracts", __name__)

FUNDING_TYPES = {"PRENEED_TRUST", "AT_NEED_DIRECT", "INSURANCE_ASSIGNMENT"}


@bp.post("/cases/<case_id>/contract")
@require("Arranger")
def create_contract(case_id):
    case = lookup.case(case_id)
    body = validate.get_json()
    funding_type = validate.require_enum(body, "funding_type", FUNDING_TYPES)

    if lookup.contract_for_case(case_id) is not None:
        raise errors.conflict(errors.ERR_CONTRACT_EXISTS,
                              "This case already has a contract")

    contract = {
        "id": db.new_id(),
        "case_id": case_id,
        "funding_type": funding_type,
        "status": "DRAFT",
    }
    db.stamp_create(contract)
    db.contracts[contract["id"]] = contract
    return ok_object(serialize.contract(contract), 201)


@bp.get("/contracts/<contract_id>")
@require("Admin", "Arranger", "TrustOfficer")
def get_contract(contract_id):
    contract = lookup.contract(contract_id)
    return ok_object(serialize.contract(contract), 200)


@bp.get("/contracts")
@require("Admin", "Arranger", "TrustOfficer")
def list_contracts():
    limit, offset = validate.pagination()
    case_id = request.args.get("case_id")
    items = list(db.contracts.values())
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.contract(c) for c in window], limit, offset, total)


@bp.post("/contracts/<contract_id>/submit-for-funding")
@require("Arranger")
def submit_for_funding(contract_id):
    contract = lookup.contract(contract_id)
    if contract["status"] != "DRAFT":
        raise errors.invalid_state("Contract can only be submitted from DRAFT")
    case = db.cases.get(contract["case_id"])
    if not case or not case.get("gfs_issued"):
        raise errors.conflict(errors.ERR_GFS_NOT_ISSUED,
                              "GFS must be issued before submitting for funding")
    contract["status"] = "PENDING_FUNDING"
    db.touch(contract)
    return ok_object(serialize.contract(contract), 200)


@bp.post("/contracts/<contract_id>/reopen")
@require("Arranger")
def reopen_contract(contract_id):
    contract = lookup.contract(contract_id)
    if contract["status"] != "PENDING_FUNDING":
        raise errors.invalid_state("Contract can only be reopened from PENDING_FUNDING")
    if contract["funding_type"] != "PRENEED_TRUST":
        raise errors.conflict(errors.ERR_NOT_AMENDABLE,
                              "Only preneed contracts may be reopened")
    contract["status"] = "DRAFT"
    db.touch(contract)
    return ok_object(serialize.contract(contract), 200)


@bp.post("/contracts/<contract_id>/mark-funded")
@require("TrustOfficer")
def mark_funded(contract_id):
    contract = lookup.contract(contract_id)
    body = validate.get_json()
    # OCC field is required on this endpoint (priority 4 well-formedness for the
    # required field, then priority 5 staleness check).
    expected = validate.require_int(body, "expected_contract_version")

    # priority 5: OCC staleness
    if expected != contract["version"]:
        raise errors.stale_version("expected_contract_version does not match current version")

    # priority 6: state
    if contract["status"] != "PENDING_FUNDING":
        raise errors.invalid_state("Contract can only be marked funded from PENDING_FUNDING")

    case = db.cases.get(contract["case_id"])

    # priority 8: segregation of duties
    if case is not None and case.get("disclosure_officer_id") is not None \
            and case["disclosure_officer_id"] == g.user_id:
        raise errors.conflict(errors.ERR_SEGREGATION_OF_DUTIES,
                              "The disclosure officer may not also fund the contract")

    # priority 12: funding sufficiency (funded >= amount), then preneed trust gate.
    funded = calc.funded_amount(contract)
    amount = calc.contract_amount(contract, case) if case else 0
    if funded < amount:
        raise errors.conflict(errors.ERR_FUNDING_SHORTFALL,
                              "funded_amount_cents is below contract_amount_cents")
    if contract["funding_type"] == "PRENEED_TRUST":
        principal = calc.trust_principal(contract["id"])
        required = calc.trust_required(contract, case) if case else 0
        if principal < required:
            raise errors.conflict(errors.ERR_TRUST_UNDERFUNDED,
                                  "trust_principal_cents is below trust_required_cents")

    contract["status"] = "FUNDED"
    db.touch(contract)
    return ok_object(serialize.contract(contract), 200)


# --------------------------------------------------------------------------
# TrustDeposit sub-resource
# --------------------------------------------------------------------------
@bp.post("/contracts/<contract_id>/trust-deposits")
@require("TrustOfficer")
def post_trust_deposit(contract_id):
    contract = lookup.contract(contract_id)
    body = validate.get_json()
    kind = validate.require_enum(body, "kind", {"PRINCIPAL", "EARNINGS", "REFUND"})
    amount_cents = validate.require_int(body, "amount_cents", minimum=1)

    deposit = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "posted_at": db.now_iso(),
    }
    db.stamp_create(deposit)
    deposit["_posted_at_seq"] = db._next_seq()
    db.trust_deposits[deposit["id"]] = deposit
    # recompute is lazy; bump the contract version to reflect funding change.
    db.touch(contract)
    return ok_object(serialize.trust_deposit(deposit), 201)


@bp.get("/contracts/<contract_id>/trust-deposits")
@require("Admin", "TrustOfficer")
def list_contract_trust_deposits(contract_id):
    lookup.contract(contract_id)
    limit, offset = validate.pagination()
    items = [d for d in db.trust_deposits.values() if d["contract_id"] == contract_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.trust_deposit(d) for d in window], limit, offset, total)


# --------------------------------------------------------------------------
# InsuranceAssignment sub-resource (create only here; actions in own route)
# --------------------------------------------------------------------------
@bp.post("/contracts/<contract_id>/insurance-assignments")
@require("TrustOfficer")
def create_insurance_assignment(contract_id):
    contract = lookup.contract(contract_id)
    body = validate.get_json()
    policy_number = validate.require_string(body, "policy_number")
    carrier = validate.require_string(body, "carrier")
    assigned_value_cents = validate.require_int(body, "assigned_value_cents", minimum=1)

    assignment = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "policy_number": policy_number,
        "carrier": carrier,
        "assigned_value_cents": assigned_value_cents,
        "status": "PENDING",
    }
    db.stamp_create(assignment)
    db.insurance_assignments[assignment["id"]] = assignment
    return ok_object(serialize.insurance_assignment(assignment), 201)
