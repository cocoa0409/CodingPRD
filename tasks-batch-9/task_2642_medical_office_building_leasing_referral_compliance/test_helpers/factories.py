"""Payload factories — one per write endpoint, input fields only."""
from itertools import count
from typing import Any, Dict

from .constants import REFERENCE_BUILDING

_npi_counter = count(1)
_suite_counter = count(1)


def next_npi() -> str:
    """A distinct well-formed 10-digit National Provider Identifier."""
    return "12345{:05d}".format(next(_npi_counter))


def next_suite_number() -> str:
    return "{:04d}".format(1000 + next(_suite_counter))


# --- Building, suite, shared space ----------------------------------------
def create_building_payload(**overrides) -> Dict[str, Any]:
    """The reference building: 100000 sf at 30.00 psf, 9.60 CAM, 400 stalls."""
    payload = {
        "name": "Meridian Medical Plaza",
        "total_rentable_sf": REFERENCE_BUILDING["total_rentable_sf"],
        "market_base_rent_psf_annual": REFERENCE_BUILDING["market_base_rent_psf_annual"],
        "operating_expense_annual_psf": REFERENCE_BUILDING["operating_expense_annual_psf"],
        "total_parking_stalls": REFERENCE_BUILDING["total_parking_stalls"],
        "patient_min_reserve_pct": REFERENCE_BUILDING["patient_min_reserve_pct"],
    }
    payload.update(overrides)
    return payload


def create_suite_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "suite_number": "210",
        "floor": 2,
        "rentable_sf": 5000,
        "suite_class": "STANDARD_EXAM",
        "power_amps_available": 200,
    }
    payload.update(overrides)
    return payload


def create_shared_space_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Level 3 Infusion Bay",
        "space_type": "INFUSION_BAY",
        "capacity_seats": 24,
        "opens_at": "07:00",
        "closes_at": "19:00",
    }
    payload.update(overrides)
    return payload


def mix_freeze_payload(frozen: bool = True, reason: str = "Referral compliance review") -> Dict[str, Any]:
    return {"frozen": frozen, "reason": reason}


# --- Tenant ---------------------------------------------------------------
def create_tenant_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": "Northgate Medical Group PC",
        "affiliation": "INDEPENDENT_PRACTICE",
        "primary_specialty": "GASTROENTEROLOGY",
        "is_physician_owned": False,
        "npi": next_npi(),
    }
    payload.update(overrides)
    return payload


# --- Lease ----------------------------------------------------------------
def create_lease_payload(building_id: str, suite_id: str, tenant_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "building_id": building_id,
        "suite_id": suite_id,
        "tenant_id": tenant_id,
        "lease_type": "DIRECT",
        "term_start": "2026-09-01",
        "term_end": "2029-08-31",
        "base_rent_psf_annual": 30.00,
    }
    payload.update(overrides)
    return payload


def patch_lease_payload(expected_lease_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_lease_version": expected_lease_version}
    payload.update(overrides)
    return payload


def attestation_payload(attestation_type: str = "SIGNED_LEASE", on_file: bool = True,
                        document_reference: str = "LSE-2642-0001") -> Dict[str, Any]:
    return {
        "attestation_type": attestation_type,
        "on_file": on_file,
        "document_reference": document_reference,
    }


def lease_compliance_decision_payload(action: str,
                                      decision_note: str = "Compliance disposition") -> Dict[str, Any]:
    return {"action": action, "decision_note": decision_note}


def terminate_payload(termination_reason: str = "MUTUAL", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


def after_hours_payload(authorized: bool) -> Dict[str, Any]:
    return {"authorized": authorized}


# --- Appraisal ------------------------------------------------------------
def create_appraisal_payload(expected_lease_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "expected_lease_version": expected_lease_version,
        "appraiser_firm": "Whitfield Valuation LLC",
        "appraisal_date": "2026-07-15",
        "opinion_low_psf": 29.00,
        "opinion_high_psf": 33.00,
        "independence_attested": True,
    }
    payload.update(overrides)
    return payload


def appraisal_decision_payload(action: str, decision_reason: str = "Independent third-party opinion") -> Dict[str, Any]:
    return {"action": action, "decision_reason": decision_reason}


# --- Tenant improvement ---------------------------------------------------
def create_ti_project_payload(suite_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "suite_id": suite_id,
        "target_suite_class": "PROCEDURE",
        "power_amps_requested": 120,
        "medical_gas_requested": False,
        "authorized_allowance_total": 100000.00,
        "landlord_share_pct": 0.60,
    }
    payload.update(overrides)
    return payload


def create_ti_line_item_payload(expected_ti_project_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "expected_ti_project_version": expected_ti_project_version,
        "description": "Procedure room casework",
        "category": "FINISHES",
        "cost_amount": 40000.00,
    }
    payload.update(overrides)
    return payload


def ti_transition_payload(action: str, note: str = "Project transition") -> Dict[str, Any]:
    return {"action": action, "note": note}


def ti_review_payload(review_type: str, decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"review_type": review_type, "decision": decision}
    payload.update(overrides)
    return payload


def complete_ti_payload(completion_note: str = "Close-out accepted") -> Dict[str, Any]:
    return {"completion_note": completion_note}


# --- Rent -----------------------------------------------------------------
def create_rent_invoice_payload(period_start: str, period_end: str, due_date: str) -> Dict[str, Any]:
    return {"period_start": period_start, "period_end": period_end, "due_date": due_date}


def payment_payload(payment_amount: float) -> Dict[str, Any]:
    return {"payment_amount": payment_amount}


def write_off_payload(write_off_justification: str = "Uncollectable arrears") -> Dict[str, Any]:
    return {"write_off_justification": write_off_justification}


# --- Compliance cases -----------------------------------------------------
def create_compliance_case_payload(tenant_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "tenant_id": tenant_id,
        "case_type": "RENT_DELINQUENCY",
        "basis": "Manual referral-compliance review",
        "severity": "LOW",
        "scoring_variant": "STRICT_CUMULATIVE",
    }
    payload.update(overrides)
    return payload


def case_transition_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --- Shared space bookings ------------------------------------------------
def create_booking_payload(shared_space_id: str, lease_id: str, window_start: str,
                           window_end: str, occupant_count: int) -> Dict[str, Any]:
    return {
        "shared_space_id": shared_space_id,
        "lease_id": lease_id,
        "window_start": window_start,
        "window_end": window_end,
        "occupant_count": occupant_count,
    }


def cancel_booking_payload(cancellation_note: str = "Cancelled by request") -> Dict[str, Any]:
    return {"cancellation_note": cancellation_note}


# --- Parking --------------------------------------------------------------
def create_parking_allocation_payload(expected_building_version: int, building_id: str,
                                      lease_id: str, category: str,
                                      stall_count: int) -> Dict[str, Any]:
    return {
        "expected_building_version": expected_building_version,
        "building_id": building_id,
        "lease_id": lease_id,
        "category": category,
        "stall_count": stall_count,
    }


def revoke_allocation_payload(revocation_note: str = "Stalls returned") -> Dict[str, Any]:
    return {"revocation_note": revocation_note}
