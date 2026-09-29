"""Payload factories.

Every factory returns a request body whose defaults satisfy the declared field
constraints, so a test only names the fields its own scenario is about.  All
money is integer cents and all rates are basis points.
"""

from typing import Any, Dict

from . import constants as C


def create_ordinance_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical ordinance vintage used by nearly every scenario."""
    payload: Dict[str, Any] = {
        "code": C.CANONICAL_ORDINANCE_CODE,
        "effective_date": C.CANONICAL_ORDINANCE_EFFECTIVE_DATE,
        "min_project_units_threshold": C.CANONICAL_MIN_PROJECT_UNITS_THRESHOLD,
        "set_aside_bps_by_district": dict(C.CANONICAL_SET_ASIDE_BPS_BY_DISTRICT),
        "gap_basis_cents_by_level": dict(C.CANONICAL_GAP_BASIS_CENTS_BY_LEVEL),
        "fee_gap_level_bps": C.CANONICAL_FEE_GAP_LEVEL_BPS,
        "surcharge_bps": C.CANONICAL_SURCHARGE_BPS,
        "surcharge_cap_cents": C.CANONICAL_SURCHARGE_CAP_CENTS,
        "discount_tiers": [dict(t) for t in C.CANONICAL_DISCOUNT_TIERS],
        "fee_due_days": C.CANONICAL_FEE_DUE_DAYS,
        "alternative_paths_allowed": list(C.CANONICAL_ALTERNATIVE_PATHS),
    }
    payload.update(overrides)
    return payload


def create_ami_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    """The 2026 area-median-income schedule."""
    payload: Dict[str, Any] = {
        "effective_year": 2026,
        "median_income_cents_by_size": dict(C.AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE),
        "utility_allowance_cents_by_bedrooms": dict(
            C.CANONICAL_UTILITY_ALLOWANCE_CENTS_BY_BEDROOMS
        ),
    }
    payload.update(overrides)
    return payload


def create_later_ami_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    """A later-year schedule that supersedes the 2026 one when published."""
    payload: Dict[str, Any] = {
        "effective_year": 2028,
        "median_income_cents_by_size": dict(C.AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE),
        "utility_allowance_cents_by_bedrooms": dict(
            C.CANONICAL_UTILITY_ALLOWANCE_CENTS_BY_BEDROOMS
        ),
    }
    payload.update(overrides)
    return payload


def create_project_payload(**overrides: Any) -> Dict[str, Any]:
    """A 20-unit R-4 development approved after the canonical ordinance."""
    payload: Dict[str, Any] = {
        "name": "Cedar Commons",
        "zoning_district": "R-4",
        "total_units": 20,
        "approval_date": "2026-03-01",
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "term_years": 55,
        "resale_formula": "AMI_INDEXED",
        "owner_appreciation_share_bps": 2500,
        "max_refinance_ltv_bps": 9000,
    }
    payload.update(overrides)
    return payload


def create_unit_payload(project_id: str, agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    """A two-bedroom rental unit that clears the comparability floor."""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "agreement_id": agreement_id,
        "unit_number": "101",
        "bedrooms": 2,
        "sqft": 900,
        "tenure": "RENTAL",
        "affordability_level_bps": 5000,
        "market_comparable_sqft": 1000,
    }
    payload.update(overrides)
    return payload


def create_marketing_plan_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    """A half-open application window: open is inclusive, close is exclusive."""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "lottery_open_at": "2026-09-01T00:00:00Z",
        "lottery_close_at": "2026-09-30T00:00:00Z",
        "preference_categories": ["LIVE_WORK", "DISPLACED"],
    }
    payload.update(overrides)
    return payload


def create_lottery_event_payload(marketing_plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "marketing_plan_id": marketing_plan_id,
        "units_offered": 1,
        "eligibility_level_bps": 5000,
    }
    payload.update(overrides)
    return payload


def create_household_payload(**overrides: Any) -> Dict[str, Any]:
    """A three-person household well under the 50%-of-AMI income limit."""
    payload: Dict[str, Any] = {
        "applicant_name": "Ada Nakamura",
        "household_size": 3,
        "gross_annual_income_cents": 6000000,
    }
    payload.update(overrides)
    return payload


def create_certification_payload(
    household_id: str, unit_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "unit_id": unit_id,
        "certified_income_cents": 6000000,
        "contract_rent_cents": 140000,
        "effective_date": "2026-09-01",
    }
    payload.update(overrides)
    return payload


def create_monitoring_review_payload(unit_id: str, **overrides: Any) -> Dict[str, Any]:
    """A clean review: rent at or under ceiling, income in range, occupancy proven."""
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "review_year": 2027,
        "reported_rent_cents": 140000,
        "reported_income_cents": 6000000,
        "occupancy_verified": True,
    }
    payload.update(overrides)
    return payload


def create_resale_payload(
    unit_id: str, expected_unit_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "expected_unit_version": expected_unit_version,
        "proposed_price_cents": 30000000,
        "appraised_value_cents": 50000000,
        "capital_improvements_cents": 0,
        "deferred_maintenance_cents": 0,
        "broker_fee_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_in_lieu_fee_payload(
    project_id: str, expected_project_version: int, basis: str = "FULL", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "basis": basis,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(
    source_fee_id: str, amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_fee_id": source_fee_id,
        "eligible_use": "AFFORDABLE_HOUSING_PRODUCTION",
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload
