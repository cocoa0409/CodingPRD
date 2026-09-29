"""Payload factories — one per resource, request-input fields only.

The PRD requires `email` to be unique across households, `license_number` to be
unique across contractors and `fiscal_year` to be unique across program years,
so the factories mint distinct values on every call unless overridden.
"""

import itertools
from typing import Any, Dict

from .constants import TEST_DEFAULTS

_email_seq = itertools.count(1)
_license_seq = itertools.count(1001)
_address_seq = itertools.count(1)
_instrument_seq = itertools.count(1)


def next_email() -> str:
    return f"household{next(_email_seq)}@example.org"


def next_license_number() -> str:
    return f"LIC-{next(_license_seq)}"


def next_address_line1() -> str:
    return f"{next(_address_seq)} Larkspur Ave"


def next_instrument_number() -> str:
    return f"INS-2026-{next(_instrument_seq):04d}"


def create_program_year_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "ami_median_income_cents": TEST_DEFAULTS["AMI_MEDIAN_INCOME_CENTS"],
        "max_loan_amount_cents": TEST_DEFAULTS["MAX_LOAN_AMOUNT_CENTS"],
        "allocation_budget_cents": TEST_DEFAULTS["ALLOCATION_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(program_year_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "program_year_id": program_year_id,
        "full_name": "Odell Marsh",
        "email": next_email(),
        "household_size": 4,
        "income_calc_method": "PART_5_ANNUAL",
        "wage_income_cents": 7_000_000,
        "benefit_income_cents": 0,
        "actual_asset_income_cents": 0,
        "household_assets_cents": 5_000_000,
        "dependents_count": 2,
        "elderly_household": False,
    }
    payload.update(overrides)
    return payload


def create_application_payload(applicant_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "applicant_id": applicant_id,
        "address_line1": next_address_line1(),
        "city": "Fairview",
        "state_code": "OH",
        "year_built": 1995,
        "assessed_value_cents": 15_000_000,
        "senior_lien_balance_cents": 12_000_000,
        "historic_district": False,
        "occupancy_type": "OWNER_OCCUPIED_SINGLE",
        "ownership_doc_type": "WARRANTY_DEED",
    }
    payload.update(overrides)
    return payload


def verify_ownership_payload(**overrides) -> Dict[str, Any]:
    payload = {"deed_recorded_date": "2015-04-12", "title_report_clear": True}
    payload.update(overrides)
    return payload


def create_inspection_payload(application_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "application_id": application_id,
        "inspection_type": "INITIAL_STANDARDS",
        "scheduled_start_at": "2026-08-03T13:00:00Z",
        "scheduled_end_at": "2026-08-03T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def record_inspection_result_payload(**overrides) -> Dict[str, Any]:
    payload = {"result": "FAIL", "deficiency_count": 3}
    payload.update(overrides)
    return payload


def create_write_up_payload(
    application_id: str, expected_application_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def create_work_item_payload(write_up_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "write_up_id": write_up_id,
        "description": "Full roof replacement",
        "category": "ROOF",
        "priority_class": "HEALTH_SAFETY",
        "estimated_cost_cents": 2_000_000,
        "is_lead_hazard_reduction": False,
        "is_historic_sensitive": False,
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": "Acme Rehab LLC",
        "license_number": next_license_number(),
        "insurance_expires_on": "2029-06-30",
        "lead_safe_certified": True,
        "historic_qualified": True,
    }
    payload.update(overrides)
    return payload


def create_bid_solicitation_payload(
    application_id: str, write_up_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "application_id": application_id,
        "write_up_id": write_up_id,
        "bid_due_at": TEST_DEFAULTS["BID_DUE_AT"],
        "min_bids_required": 1,
    }
    payload.update(overrides)
    return payload


def create_bid_payload(
    solicitation_id: str, contractor_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "solicitation_id": solicitation_id,
        "contractor_id": contractor_id,
        "amount_cents": 2_000_000,
        "proposed_start_date": TEST_DEFAULTS["PROPOSED_START_DATE"],
        "proposed_end_date": TEST_DEFAULTS["PROPOSED_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_loan_payload(application_id: str, **overrides) -> Dict[str, Any]:
    payload = {"application_id": application_id, "structure_type": "DEFERRED"}
    payload.update(overrides)
    if payload["structure_type"] in ("DEFERRED", "FORGIVABLE"):
        payload.setdefault("forgiveness_term_months", 120)
    return payload


def record_lien_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "lien_position": 2,
        "recorded_instrument_number": next_instrument_number(),
    }
    payload.update(overrides)
    return payload


def create_draw_request_payload(
    loan_id: str, contractor_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "loan_id": loan_id,
        "contractor_id": contractor_id,
        "requested_amount_cents": 1_000_000,
        "is_final_draw": False,
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(
    loan_id: str, expected_loan_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "loan_id": loan_id,
        "expected_loan_version": expected_loan_version,
        "amount_delta_cents": 100_000,
        "justification": "Concealed rot discovered behind the porch sheathing",
        "affects_lead_hazard_work": False,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(
    contractor_id: str, application_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "contractor_id": contractor_id,
        "application_id": application_id,
        "defect_category": "WORKMANSHIP",
        "description": "The new roof leaks at the north valley after the first storm",
    }
    payload.update(overrides)
    return payload


def contractor_status_payload(approved_list_status: str, **overrides) -> Dict[str, Any]:
    payload = {"approved_list_status": approved_list_status, "reason": "Program review"}
    payload.update(overrides)
    return payload


def lead_clearance_payload(**overrides) -> Dict[str, Any]:
    payload = {"risk_assessment_completed": True, "hazard_control_method": "ABATEMENT"}
    payload.update(overrides)
    return payload


def historic_clearance_payload(**overrides) -> Dict[str, Any]:
    payload = {"shpo_review_outcome": "NO_ADVERSE_EFFECT"}
    payload.update(overrides)
    return payload


def close_out_payload(**overrides) -> Dict[str, Any]:
    payload = {"completion_date": "2026-11-30"}
    payload.update(overrides)
    return payload


def recapture_payload(recapture_event_type: str, **overrides) -> Dict[str, Any]:
    payload = {
        "recapture_event_type": recapture_event_type,
        "recapture_event_date": "2027-11-30",
    }
    if recapture_event_type == "SALE":
        payload.update(
            {
                "sale_price_cents": 20_000_000,
                "closing_costs_cents": 1_000_000,
                "homeowner_investment_cents": 0,
            }
        )
    payload.update(overrides)
    return payload


def loan_payment_payload(**overrides) -> Dict[str, Any]:
    payload = {"amount_cents": 100_000, "payment_date": "2027-01-31"}
    payload.update(overrides)
    return payload
