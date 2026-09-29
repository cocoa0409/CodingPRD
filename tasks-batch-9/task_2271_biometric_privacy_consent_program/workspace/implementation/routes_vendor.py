"""Vendors, attestations and the vendor contract lifecycle (Cascade A)."""

from flask import Blueprint

import constants as K
import serialize
from authz import actor, require_role, require_role_for_target
from calc import refresh_contract_compliance_score, refresh_vendor_risk_score
from common import respond, respond_list
from errors import fail
from ops import cascade_a
from store import add_days, db, new_record, ordered, touch
from validate import (
    body,
    find_contract,
    find_program,
    find_vendor,
    opt_bool,
    query_enum,
    query_str,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("vendors", __name__)

VENDOR_READ_ROLES = ("SystemOperator", "PrivacyOfficer", "ComplianceApprover", "VendorManager")

ATTESTATION_EDGES = {
    "NOT_REQUESTED": ("REQUESTED",),
    "REQUESTED": ("RECEIVED", "REJECTED"),
    "REJECTED": ("REQUESTED",),
    "RECEIVED": (),
}

CONTRACT_GRANTS = {
    "APPROVED": ("ComplianceApprover",),
    "EXECUTED": ("VendorManager",),
    "TERMINATED": ("VendorManager",),
    "CLOSED_OUT": ("VendorManager",),
    "VOID": ("VendorManager",),
    "DRAFT": (),
}


# --- Vendor -----------------------------------------------------------------

@bp.post("/vendors")
def create_vendor():
    _, role = actor()
    require_role(role, ("VendorManager",))
    data = body()
    program_id = req_str(data, "program_id")
    name = req_str(data, "name")
    sells = req_bool(data, "sells_biometric_data")
    subprocessor_count = req_int(data, "subprocessor_count", minimum=0)
    deletion_sla_days = req_int(data, "deletion_sla_days", minimum=0)
    disclosure_complete = opt_bool(data, "subprocessor_disclosure_complete", default=False)

    program = find_program(program_id)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "name": name,
            "sells_biometric_data": sells,
            "subprocessor_count": subprocessor_count,
            "subprocessor_disclosure_complete": disclosure_complete,
            "deletion_sla_days": deletion_sla_days,
            "attestation_status": "NOT_REQUESTED",
            "risk_score": 0,
        }
    )
    refresh_vendor_risk_score(rec)
    db.vendors[rec["id"]] = rec
    touch(program)
    return respond(serialize.vendor, rec, 201)


@bp.post("/vendors/<vendor_id>/attestations")
def record_attestation(vendor_id):
    _, role = actor()
    require_role(role, ("VendorManager",))
    data = body()
    to_status = req_enum(data, "attestation_status", K.ATTESTATION_STATUSES)
    disclosure_complete = opt_bool(data, "subprocessor_disclosure_complete")

    vendor = find_vendor(vendor_id)

    if to_status not in ATTESTATION_EDGES[vendor["attestation_status"]]:
        fail(
            "ERR_INVALID_TRANSITION",
            "Attestation cannot move from %s to %s."
            % (vendor["attestation_status"], to_status),
        )

    vendor["attestation_status"] = to_status
    if disclosure_complete is not None:
        vendor["subprocessor_disclosure_complete"] = disclosure_complete
    refresh_vendor_risk_score(vendor)
    for contract in ordered(list(db.contracts.values())):
        if contract["vendor_id"] == vendor_id and contract["status"] not in (
            "VOID",
            "CLOSED_OUT",
        ):
            refresh_contract_compliance_score(contract)
    touch(vendor)
    return respond(serialize.vendor, vendor)


@bp.get("/vendors/<vendor_id>")
def read_vendor(vendor_id):
    _, role = actor()
    require_role(role, VENDOR_READ_ROLES)
    vendor = find_vendor(vendor_id)
    return respond(serialize.vendor, vendor)


@bp.get("/vendors")
def list_vendors():
    _, role = actor()
    require_role(role, VENDOR_READ_ROLES)
    program_id = query_str("program_id")
    rows = list(db.vendors.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    return respond_list(rows, serialize.vendor)


# --- VendorContract ---------------------------------------------------------

@bp.post("/vendor-contracts")
def create_contract():
    user_id, role = actor()
    require_role(role, ("VendorManager",))
    data = body()
    vendor_id = req_str(data, "vendor_id")
    prohibits_sale = req_bool(data, "prohibits_sale")
    restricts_disclosure = req_bool(data, "restricts_disclosure")
    requires_deletion = req_bool(data, "requires_deletion_on_termination")
    deletion_deadline_days = req_int(data, "deletion_deadline_days", minimum=0)
    indemnity_cap_cents = req_int(data, "indemnity_cap_cents", minimum=0)
    effective_from = req_datetime(data, "effective_from")

    find_vendor(vendor_id)

    rec = new_record()
    rec.update(
        {
            "vendor_id": vendor_id,
            "prohibits_sale": prohibits_sale,
            "restricts_disclosure": restricts_disclosure,
            "requires_deletion_on_termination": requires_deletion,
            "deletion_deadline_days": deletion_deadline_days,
            "indemnity_cap_cents": indemnity_cap_cents,
            "effective_from": effective_from,
            "compliance_score": 0,
            "status": "DRAFT",
            "drafted_by_user_id": user_id,
            "approved_by_user_id": None,
            "terminated_at": None,
            "deletion_deadline_at": None,
            "deletion_certificate_ref": None,
        }
    )
    db.contracts[rec["id"]] = rec
    refresh_contract_compliance_score(rec)
    return respond(serialize.contract, rec, 201)


@bp.post("/vendor-contracts/<contract_id>/transitions")
def contract_transition(contract_id):
    user_id, role = actor()
    raw = body()
    require_role_for_target(
        role,
        raw.get("to_status"),
        K.CONTRACT_STATUSES,
        CONTRACT_GRANTS,
        ("ComplianceApprover", "VendorManager"),
    )
    to_status = req_enum(raw, "to_status", K.CONTRACT_STATUSES)
    certificate_ref = None
    if to_status == "CLOSED_OUT":
        certificate_ref = req_str(raw, "deletion_certificate_ref")

    contract = find_contract(contract_id)
    current = contract["status"]

    # step 7: separation of duties precedes transition legality
    if to_status == "APPROVED" and user_id == contract["drafted_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver must differ from the user who drafted the contract.",
        )

    edges = {
        ("DRAFT", "APPROVED"),
        ("APPROVED", "EXECUTED"),
        ("EXECUTED", "TERMINATED"),
        ("TERMINATED", "CLOSED_OUT"),
        ("DRAFT", "VOID"),
    }
    if (current, to_status) not in edges:
        fail("ERR_INVALID_TRANSITION", "A contract cannot move from %s to %s." % (current, to_status))

    if to_status == "APPROVED":
        if not (
            contract["prohibits_sale"]
            and contract["restricts_disclosure"]
            and contract["requires_deletion_on_termination"]
        ):
            fail(
                "ERR_VENDOR_CONTRACT_NONCOMPLIANT",
                "All three statutory clauses must be present before approval.",
            )
        contract["approved_by_user_id"] = user_id
        contract["status"] = "APPROVED"
        refresh_contract_compliance_score(contract)
        touch(contract)

    elif to_status == "EXECUTED":
        refresh_contract_compliance_score(contract)
        if contract["compliance_score"] < K.CONTRACT_SCORE_FLOOR:
            fail(
                "ERR_CONTRACT_SCORE_BELOW_FLOOR",
                "The contract compliance score is below the %s floor."
                % K.CONTRACT_SCORE_FLOOR,
            )
        for other in db.contracts.values():
            if (
                other["id"] != contract["id"]
                and other["vendor_id"] == contract["vendor_id"]
                and other["status"] == "EXECUTED"
            ):
                fail(
                    "ERR_DUPLICATE_EXECUTED_CONTRACT",
                    "This vendor already carries an executed contract.",
                )
        contract["status"] = "EXECUTED"
        touch(contract)

    elif to_status == "TERMINATED":
        contract["status"] = "TERMINATED"
        contract["terminated_at"] = db.clock
        contract["deletion_deadline_at"] = add_days(
            contract["terminated_at"], contract["deletion_deadline_days"]
        )
        touch(contract)
        cascade_a(contract)

    elif to_status == "CLOSED_OUT":
        if contract["deletion_deadline_at"] is not None and db.clock > contract["deletion_deadline_at"]:
            fail(
                "ERR_DELETION_DEADLINE_MISSED",
                "The contractual deletion deadline has already passed.",
            )
        contract["deletion_certificate_ref"] = certificate_ref
        contract["status"] = "CLOSED_OUT"
        touch(contract)

    else:  # VOID
        contract["status"] = "VOID"
        touch(contract)

    return respond(serialize.contract, contract)


@bp.get("/vendor-contracts/<contract_id>")
def read_contract(contract_id):
    _, role = actor()
    require_role(role, VENDOR_READ_ROLES)
    contract = find_contract(contract_id)
    return respond(serialize.contract, contract)


@bp.get("/vendor-contracts")
def list_contracts():
    _, role = actor()
    require_role(role, VENDOR_READ_ROLES)
    vendor_id = query_str("vendor_id")
    status = query_enum("status", K.CONTRACT_STATUSES)
    rows = list(db.contracts.values())
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.contract)
