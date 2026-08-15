"""Vendors and vendor contracts."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_contract, ser_vendor
from services.core import base_entity, created_asc, touch
from services.risk import (CLAUSE_CODES, DATA_CATEGORIES, REGIONS, clause_gap,
                           vendor_risk_tier)

bp = Blueprint("vendors", __name__)


@bp.post("/privacy/vendors")
def create_vendor():
    require_roles("VendorManager")
    body = get_body()
    vendor_name = body.get("vendor_name")
    home_region = body.get("home_region")
    processes_categories = body.get("processes_categories")
    if not isinstance(vendor_name, str) or not vendor_name:
        raise ApiError("ERR_INVALID_REQUEST", "vendor_name is required")
    if home_region not in REGIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid home_region")
    if (not isinstance(processes_categories, list)
            or any(c not in DATA_CATEGORIES for c in processes_categories)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "processes_categories must be a list of data categories")
    vendor = base_entity()
    vendor.update({
        "vendor_name": vendor_name,
        "home_region": home_region,
        "processes_categories": list(processes_categories),
        "risk_tier": vendor_risk_tier(processes_categories),
        "status": "ONBOARDING",
    })
    db.vendors[vendor["id"]] = vendor
    return success(ser_vendor(vendor), 201)


@bp.get("/privacy/vendors/<vendor_id>")
def get_vendor(vendor_id):
    require_roles(*STAFF_ROLES)
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    return success(ser_vendor(vendor), 200)


@bp.post("/privacy/vendors/<vendor_id>/submit-assessment")
def submit_vendor_assessment(vendor_id):
    require_roles("VendorManager")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    if vendor["status"] != "ONBOARDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "vendor must be ONBOARDING")
    vendor["status"] = "ASSESSMENT"
    touch(vendor)
    return success(ser_vendor(vendor), 200)


@bp.post("/privacy/vendors/<vendor_id>/approve")
def approve_vendor(vendor_id):
    require_roles("PrivacyAdmin")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    if vendor["status"] != "ASSESSMENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "vendor must be ASSESSMENT")
    has_executed = any(
        c["vendor_id"] == vendor_id and c["status"] == "EXECUTED"
        for c in db.contracts.values()
    )
    if not has_executed:
        raise ApiError("ERR_NO_EXECUTED_CONTRACT",
                       "vendor has no EXECUTED contract")
    vendor["status"] = "APPROVED"
    touch(vendor)
    return success(ser_vendor(vendor), 200)


@bp.post("/privacy/vendors/<vendor_id>/reject")
def reject_vendor(vendor_id):
    require_roles("PrivacyAdmin")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    if vendor["status"] != "ASSESSMENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "vendor must be ASSESSMENT")
    vendor["status"] = "REJECTED"
    touch(vendor)
    return success(ser_vendor(vendor), 200)


@bp.post("/privacy/vendors/<vendor_id>/offboard")
def offboard_vendor(vendor_id):
    require_roles("PrivacyAdmin")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    if vendor["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "vendor must be APPROVED")
    vendor["status"] = "OFFBOARDED"
    touch(vendor)
    superseded = [c for c in db.contracts.values()
                  if c["vendor_id"] == vendor_id
                  and c["status"] in ("DRAFT", "VERIFIED", "EXECUTED")]
    formerly_executed_ids = []
    for contract in created_asc(superseded):
        if contract["status"] == "EXECUTED":
            formerly_executed_ids.append(contract["id"])
        contract["status"] = "SUPERSEDED"
        touch(contract)
    suspended = [t for t in db.transfers.values()
                 if t["vendor_contract_id"] in formerly_executed_ids
                 and t["status"] == "APPROVED"]
    for transfer in created_asc(suspended):
        transfer["status"] = "SUSPENDED"
        transfer["suspension_reason"] = "CONTRACT_SUPERSEDED"
        touch(transfer)
    rejected = [t for t in db.transfers.values()
                if t["vendor_id"] == vendor_id
                and t["status"] in ("PROPOSED", "UNDER_ASSESSMENT")]
    for transfer in created_asc(rejected):
        transfer["status"] = "REJECTED"
        touch(transfer)
    return success(ser_vendor(vendor), 200)


# --- VendorContract --------------------------------------------------------------

@bp.post("/privacy/vendors/<vendor_id>/contracts")
def create_contract(vendor_id):
    require_roles("VendorManager")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    body = get_body()
    if "expected_vendor_version" in body:
        if body["expected_vendor_version"] != vendor["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_vendor_version does not match the current version")
    provided_clauses = body.get("provided_clauses")
    if "expected_vendor_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "expected_vendor_version is required")
    if (not isinstance(provided_clauses, list)
            or any(c not in CLAUSE_CODES for c in provided_clauses)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "provided_clauses must be a list of clause codes")
    predecessors = [c for c in db.contracts.values()
                    if c["vendor_id"] == vendor_id
                    and c["status"] in ("DRAFT", "VERIFIED")]
    for predecessor in created_asc(predecessors):
        predecessor["status"] = "SUPERSEDED"
        touch(predecessor)
    required, missing = clause_gap(vendor["risk_tier"], provided_clauses)
    contract = base_entity()
    contract.update({
        "vendor_id": vendor_id,
        "provided_clauses": list(provided_clauses),
        "required_clauses": required,
        "missing_clauses": missing,
        "verification_status": "UNVERIFIED",
        "status": "DRAFT",
    })
    db.contracts[contract["id"]] = contract
    touch(vendor)
    return success(ser_contract(contract), 201)


@bp.get("/privacy/vendors/<vendor_id>/contracts")
def list_contracts(vendor_id):
    require_roles(*STAFF_ROLES)
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", "vendor not found")
    items = created_asc([c for c in db.contracts.values()
                         if c["vendor_id"] == vendor_id])
    return list_response(items, ser_contract)


@bp.post("/privacy/contracts/<contract_id>/verify")
def verify_contract(contract_id):
    require_roles("LegalCounsel")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", "contract not found")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a DRAFT contract can be verified")
    vendor = db.vendors.get(contract["vendor_id"])
    required, missing = clause_gap(vendor["risk_tier"], contract["provided_clauses"])
    contract["required_clauses"] = required
    contract["missing_clauses"] = missing
    if not missing:
        contract["verification_status"] = "PASSED"
        contract["status"] = "VERIFIED"
    else:
        contract["verification_status"] = "FAILED"
    touch(contract)
    return success(ser_contract(contract), 200)


@bp.post("/privacy/contracts/<contract_id>/execute")
def execute_contract(contract_id):
    require_roles("VendorManager")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", "contract not found")
    if contract["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a VERIFIED contract can be executed")
    vendor = db.vendors.get(contract["vendor_id"])
    if vendor is not None and vendor["status"] in ("REJECTED", "OFFBOARDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "owning vendor is REJECTED or OFFBOARDED")
    contract["status"] = "EXECUTED"
    touch(contract)
    return success(ser_contract(contract), 200)
