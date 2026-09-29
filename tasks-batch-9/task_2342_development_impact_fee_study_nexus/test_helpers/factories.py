"""Request-body builders for every write endpoint.

Each builder returns a valid minimal-or-canonical body and accepts keyword
overrides so a test can vary exactly the one field it is about.
"""

from typing import Optional

from .constants import (
    CREDIT_TYPE_EXISTING_TAX_CONTRIBUTION,
    DECISION_APPROVE_FULL,
    DEFERRAL_DECISION_EXECUTE,
    LAND_USE_SINGLE_FAMILY,
    METHODOLOGY_PLAN_BASED,
    NOTICE_NEWSPAPER,
    PARKS_CODE,
    PARKS_EXISTING_LOS,
    PARKS_PLANNED_LOS,
    PARKS_SINGLE_FAMILY_CONVERSION_FACTOR,
    PARKS_UNIT_COST_CENTS,
    ROADS_CODE,
    ROADS_EXISTING_LOS,
    ROADS_PLANNED_LOS,
    ROADS_SINGLE_FAMILY_CONVERSION_FACTOR,
    ROADS_UNIT_COST_CENTS,
    SECURITY_CASH_BOND,
    TRIGGER_PERMIT,
    UNIT_BASIS_PER_DWELLING,
    VALUATION_NOMINAL,
)
from .types import Payload


def _merged(base: Payload, overrides: Payload) -> Payload:
    body = dict(base)
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Fee programs
# ---------------------------------------------------------------------------
def fee_program_payload(**overrides) -> Payload:
    """A program body carrying only the two required fields."""
    return _merged(
        {"name": "City of Harbor Impact Fee Program", "jurisdiction_code": "HARBOR"},
        overrides,
    )


def second_fee_program_payload(**overrides) -> Payload:
    """A second, independent program under a different jurisdiction code."""
    return _merged(
        {"name": "City of Seagate Impact Fee Program", "jurisdiction_code": "SEAGATE"},
        overrides,
    )


def fully_specified_fee_program_payload(**overrides) -> Payload:
    """A program body that supplies every tunable statutory constant."""
    return _merged(
        {
            "name": "City of Seagate Impact Fee Program",
            "jurisdiction_code": "SEAGATE",
            "fiscal_year_start_month": 10,
            "statutory_expenditure_deadline_years": 7,
            "notice_min_days": 21,
            "protest_threshold_bp": 6000,
            "effective_delay_days": 90,
            "admin_charge_bp": 450,
            "credit_cap_bp": 7500,
            "los_policy": "PLANNED_STANDARD_ALLOWED",
            "discount_rate_bp": 550,
            "max_deferral_days": 900,
            "default_penalty_bp": 1500,
            "at_risk_window_days": 400,
            "report_grace_days": 200,
        },
        overrides,
    )


def annual_report_filing_payload(fiscal_year: int, **overrides) -> Payload:
    return _merged({"fiscal_year": fiscal_year}, overrides)


# ---------------------------------------------------------------------------
# Facility categories
# ---------------------------------------------------------------------------
def parks_category_payload(program_id: str, **overrides) -> Payload:
    """The parks facility standard used throughout the worked examples."""
    return _merged(
        {
            "fee_program_id": program_id,
            "code": PARKS_CODE,
            "name": "Neighborhood Parks",
            "demand_unit_label": "resident",
            "existing_los_per_demand_unit": PARKS_EXISTING_LOS,
            "planned_los_per_demand_unit": PARKS_PLANNED_LOS,
            "unit_cost_cents": PARKS_UNIT_COST_CENTS,
        },
        overrides,
    )


def roads_category_payload(program_id: str, **overrides) -> Payload:
    """The arterial roads facility standard, whose planned standard sits below
    its existing one."""
    return _merged(
        {
            "fee_program_id": program_id,
            "code": ROADS_CODE,
            "name": "Arterial Roads",
            "demand_unit_label": "trip",
            "existing_los_per_demand_unit": ROADS_EXISTING_LOS,
            "planned_los_per_demand_unit": ROADS_PLANNED_LOS,
            "unit_cost_cents": ROADS_UNIT_COST_CENTS,
        },
        overrides,
    )


def expenditure_payload(
    amount_cents: int, expected_facility_category_version: int, **overrides
) -> Payload:
    return _merged(
        {
            "amount_cents": amount_cents,
            "project_name": "Harborview Park Phase One",
            "expected_facility_category_version": expected_facility_category_version,
        },
        overrides,
    )


def refund_payload(**overrides) -> Payload:
    return _merged({"reason": "Statutory deadline reached"}, overrides)


# ---------------------------------------------------------------------------
# Fee studies
# ---------------------------------------------------------------------------
def fee_study_payload(
    program_id: str, expected_fee_program_version: int, **overrides
) -> Payload:
    return _merged(
        {
            "fee_program_id": program_id,
            "title": "2026 Impact Fee Study",
            "methodology": METHODOLOGY_PLAN_BASED,
            "expected_fee_program_version": expected_fee_program_version,
        },
        overrides,
    )


def notice_payload(**overrides) -> Payload:
    return _merged({"notice_method": NOTICE_NEWSPAPER, "notice_days": 30}, overrides)


def protest_filing_payload(**overrides) -> Payload:
    return _merged(
        {"protester_name": "Harbor Heights Owners", "parcel_count": 12, "weight_bp": 3000},
        overrides,
    )


# ---------------------------------------------------------------------------
# Nexus components
# ---------------------------------------------------------------------------
def parks_component_payload(
    study_id: str, facility_category_id: str, **overrides
) -> Payload:
    """Parks projection: 1,200 dwellings at 2.5000 demand units each."""
    return _merged(
        {
            "fee_study_id": study_id,
            "facility_category_id": facility_category_id,
            "horizon_start_year": 2026,
            "horizon_end_year": 2030,
            "projected_new_dwelling_units": 1200,
            "projected_new_nonres_sqft": 0,
            "demand_units_per_dwelling": 2.5000,
            "demand_units_per_1000_nonres_sqft": 0.0000,
            "planned_facility_cost_cents": 500000000,
            "planned_other_funding_cents": 50000000,
            "planned_growth_share_bp": 8000,
            "planned_capacity_demand_units": 3500.0000,
            "existing_tax_credit_per_unit_cents": 15000,
        },
        overrides,
    )


def roads_component_payload(
    study_id: str, facility_category_id: str, **overrides
) -> Payload:
    """Roads projection: 1,200 dwellings at 1.0100 plus 200,000 square feet at
    3.7500 per thousand."""
    return _merged(
        {
            "fee_study_id": study_id,
            "facility_category_id": facility_category_id,
            "horizon_start_year": 2026,
            "horizon_end_year": 2030,
            "projected_new_dwelling_units": 1200,
            "projected_new_nonres_sqft": 200000,
            "demand_units_per_dwelling": 1.0100,
            "demand_units_per_1000_nonres_sqft": 3.7500,
            "planned_facility_cost_cents": 900000000,
            "planned_other_funding_cents": 100000000,
            "planned_growth_share_bp": 6500,
            "planned_capacity_demand_units": 2000.0000,
            "existing_tax_credit_per_unit_cents": 0,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Fee schedule lines
# ---------------------------------------------------------------------------
def schedule_item_payload(**overrides) -> Payload:
    """A single-family per-dwelling line against the parks conversion factor."""
    return _merged(
        {
            "land_use_category": LAND_USE_SINGLE_FAMILY,
            "unit_basis": UNIT_BASIS_PER_DWELLING,
            "conversion_factor": PARKS_SINGLE_FAMILY_CONVERSION_FACTOR,
        },
        overrides,
    )


def roads_schedule_item_payload(**overrides) -> Payload:
    """A single-family per-dwelling line against the roads conversion factor."""
    return _merged(
        {
            "land_use_category": LAND_USE_SINGLE_FAMILY,
            "unit_basis": UNIT_BASIS_PER_DWELLING,
            "conversion_factor": ROADS_SINGLE_FAMILY_CONVERSION_FACTOR,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Development applications
# ---------------------------------------------------------------------------
def development_application_payload(program_id: str, **overrides) -> Payload:
    """A ten-dwelling single-family project collected at permit."""
    return _merged(
        {
            "fee_program_id": program_id,
            "permit_number": "BP-1001",
            "land_use_category": LAND_USE_SINGLE_FAMILY,
            "collection_trigger": TRIGGER_PERMIT,
            "dwelling_units": 10,
            "nonres_sqft": 0,
        },
        overrides,
    )


def payment_payload(amount_cents: int, **overrides) -> Payload:
    return _merged(
        {"amount_cents": amount_cents, "payment_reference": "WIRE-11"}, overrides
    )


# ---------------------------------------------------------------------------
# Credit claims
# ---------------------------------------------------------------------------
def credit_claim_payload(**overrides) -> Payload:
    """Ten years of a 120,000-cent annual tax contribution, valued nominally."""
    return _merged(
        {
            "facility_category_code": PARKS_CODE,
            "credit_type": CREDIT_TYPE_EXISTING_TAX_CONTRIBUTION,
            "valuation_method": VALUATION_NOMINAL,
            "annual_tax_contribution_cents": 120000,
            "contribution_years": 10,
        },
        overrides,
    )


def credit_decision_payload(
    expected_development_application_version: int,
    decision: str = DECISION_APPROVE_FULL,
    approved_cents: Optional[int] = None,
    **overrides,
) -> Payload:
    body: Payload = {
        "decision": decision,
        "expected_development_application_version": expected_development_application_version,
    }
    if approved_cents is not None:
        body["approved_cents"] = approved_cents
    return _merged(body, overrides)


# ---------------------------------------------------------------------------
# Deferral agreements
# ---------------------------------------------------------------------------
def deferral_agreement_payload(
    security_amount_cents: int, requested_due_at: str, **overrides
) -> Payload:
    return _merged(
        {
            "requested_security_type": SECURITY_CASH_BOND,
            "security_amount_cents": security_amount_cents,
            "requested_due_at": requested_due_at,
        },
        overrides,
    )


def deferral_decision_payload(decision: str = DEFERRAL_DECISION_EXECUTE, **overrides) -> Payload:
    return _merged({"decision": decision}, overrides)
