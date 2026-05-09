"""Contract action routes."""
from flask import Blueprint

from common import (
    check_version,
    get_allocation_or_404,
    get_application_or_404,
    get_contract_or_404,
    get_json_body,
    get_program_or_404,
    require_field,
    require_int,
    stamp_update,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.calc import compute_monthly_effective_rent
from services.sync import latest_event

bp = Blueprint("contracts", __name__)


# ----------------------------------------------------------------------------
# GET /contracts/{contractId}
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/contracts/<contract_id>")
def get_contract(program_id, contract_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    contract = get_contract_or_404(program_id, contract_id)
    return success(contract)


# ----------------------------------------------------------------------------
# POST /contracts/{contractId}/pay-deposit  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/contracts/<contract_id>/pay-deposit")
def pay_deposit(program_id, contract_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    contract = get_contract_or_404(program_id, contract_id)
    body = get_json_body()
    check_version(contract, body)

    application = get_application_or_404(program_id, contract["application_id"])
    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may pay the deposit")

    with db.lock:
        # State preconditions in priority order:
        if contract.get("status") != "DRAFT":
            raise api_error("ERR_CONTRACT_NOT_IN_DRAFT",
                            "Contract must be DRAFT")
        allocation = get_allocation_or_404(program_id, contract["allocation_id"])
        if allocation.get("status") != "CONFIRMED":
            raise api_error("ERR_ALLOCATION_NOT_CONFIRMED",
                            "Allocation must be CONFIRMED")

        # Latest PAYMENT_DEPOSIT for this contract must match
        evt = latest_event(event_type="PAYMENT_DEPOSIT", subject_id=contract_id)
        if evt is None:
            raise api_error("ERR_DEPOSIT_AMOUNT_MISMATCH",
                            "No PAYMENT_DEPOSIT event found")
        amt = (evt.get("payload") or {}).get("amount_cents")
        try:
            amt = int(amt)
        except (TypeError, ValueError):
            raise api_error("ERR_DEPOSIT_AMOUNT_MISMATCH",
                            "Invalid deposit payment amount")
        if amt != int(contract["deposit_amount_cents"]):
            raise api_error("ERR_DEPOSIT_AMOUNT_MISMATCH",
                            "Deposit amount does not match contract")

        contract["deposit_paid"] = True
        contract["status"] = "DEPOSIT_PAID"
        stamp_update(contract)
    return success(contract)


# ----------------------------------------------------------------------------
# POST /contracts/{contractId}/sign
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/contracts/<contract_id>/sign")
def sign_contract(program_id, contract_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    contract = get_contract_or_404(program_id, contract_id)
    body = get_json_body()
    check_version(contract, body)

    application = get_application_or_404(program_id, contract["application_id"])
    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may sign this contract")

    with db.lock:
        if contract.get("status") != "DEPOSIT_PAID":
            raise api_error("ERR_CONTRACT_NOT_DEPOSIT_PAID",
                            "Contract must be DEPOSIT_PAID")

        signature = body.get("signature_blob")
        if not isinstance(signature, str) or not signature:
            raise api_error("ERR_INVALID_REQUEST",
                            "signature_blob must be a non-empty string")
        lease_start = require_int(body, "lease_start_period")
        lease_end = require_int(body, "lease_end_period")
        allocation = get_allocation_or_404(program_id, contract["allocation_id"])
        confirmation_period = allocation.get("confirmation_period")
        if confirmation_period is None:
            confirmation_period = 0
        if lease_end <= lease_start or lease_start < int(confirmation_period):
            raise api_error("ERR_INVALID_LEASE_TERM", "Invalid lease term")

        contract["signature_blob"] = signature
        contract["lease_start_period"] = lease_start
        contract["lease_end_period"] = lease_end
        contract["status"] = "SIGNED"
        stamp_update(contract)
    return success(contract)


# ----------------------------------------------------------------------------
# POST /contracts/{contractId}/handover  — HousingOfficer
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/contracts/<contract_id>/handover")
def handover_contract(program_id, contract_id):
    require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    contract = get_contract_or_404(program_id, contract_id)
    body = get_json_body()
    check_version(contract, body)

    with db.lock:
        if contract.get("status") != "SIGNED":
            raise api_error("ERR_CONTRACT_NOT_SIGNED",
                            "Contract must be SIGNED")
        cpi = int(program["current_period_index"])
        if cpi < int(contract["lease_start_period"]):
            raise api_error("ERR_LEASE_NOT_STARTED",
                            "Lease has not started yet")

        contract["handover_recorded"] = True
        contract["status"] = "ACTIVE"
        contract["monthly_effective_rent_cents"] = compute_monthly_effective_rent(
            contract, current_period_index=cpi)
        stamp_update(contract)

        # Cascades: application → OCCUPIED, unit → OCCUPIED
        application = db.applications.get(contract["application_id"])
        if application and application.get("status") == "ALLOCATED":
            application["status"] = "OCCUPIED"
            stamp_update(application)
        unit = db.housing_units.get(contract["housing_unit_id"])
        if unit and unit.get("status") in {"RESERVED", "AVAILABLE"}:
            unit["status"] = "OCCUPIED"
            stamp_update(unit)
    return success(contract)
