"""Payload factories — one per entity, input fields only."""
from .constants import (
    BASE_WEIGHT_VALUE, BASE_WEIGHT_FRONTAGE, BASE_WEIGHT_SQFT,
)

DEFAULTS = {
    "AUTH_EXPIRES": "2031-05-01T00:00:00Z",
}


def create_bid_payload(**overrides) -> dict:
    """District create body (§3.1). min/max_assessment_cents omitted -> server defaults."""
    defaults = {
        "name": "Test BID",
        "boundary_description": "Test boundary",
        "authorization_expires_at": DEFAULTS["AUTH_EXPIRES"],
        "assessment_weight_value": BASE_WEIGHT_VALUE,
        "assessment_weight_frontage": BASE_WEIGHT_FRONTAGE,
        "assessment_weight_sqft": BASE_WEIGHT_SQFT,
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    """Parcel create body (§3.1). Canonical COMMERCIAL parcel -> weighted_base 700."""
    defaults = {
        "apn": "APN-1",
        "owner_name": "Test Owner",
        "use_class": "COMMERCIAL",
        "assessed_value_cents": 100000000,
        "linear_frontage_ft": 50,
        "building_sqft": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_fiscal_year_payload(**overrides) -> dict:
    """Fiscal year create body (§3.2). Half-open [start_date, end_date)."""
    defaults = {
        "year_label": "FY2028",
        "start_date": "2027-07-01T00:00:00Z",
        "end_date": "2028-07-01T00:00:00Z",
        "assessment_due_date": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    """Budget create body (§3.2)."""
    defaults = {
        "total_expenditure_cents": 4025000,
        "other_revenue_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_work_plan_line_payload(**overrides) -> dict:
    """Work-plan line create body (§3.2)."""
    defaults = {
        "category": "CLEAN",
        "allocated_amount_cents": 4025000,
    }
    defaults.update(overrides)
    return defaults


def create_reallocation_payload(**overrides) -> dict:
    """Reallocation body (§3.2, §2.7)."""
    defaults = {
        "from_category": "SAFE",
        "to_category": "CLEAN",
        "amount_cents": 500000,
        "expected_budget_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    """Payment body (§3.4). method optional -> server default TAX_ROLL."""
    defaults = {
        "amount_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    """Dispute filing body (§3.5). reason optional."""
    defaults = {
        "claimed_value_cents": 40000000,
        "requested_amount_cents": 3000000,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_petition_payload(**overrides) -> dict:
    """Petition create body (§3.6). required_threshold_pct / renewal_term_months optional."""
    defaults = {
        "circulation_deadline": "2027-06-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_signature_payload(**overrides) -> dict:
    """Petition signature body (§3.6)."""
    defaults = {
        "support": True,
    }
    defaults.update(overrides)
    return defaults


def create_ambassador_payload(**overrides) -> dict:
    """Ambassador create body (§3.7)."""
    defaults = {
        "name": "Test Ambassador",
        "service_role": "CLEAN",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    """Ambassador shift body (§3.7)."""
    defaults = {
        "zone": "Zone-1",
        "start_at": "2026-06-01T08:00:00Z",
        "end_at": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(**overrides) -> dict:
    """Service request body (§3.7). external_ref / description optional."""
    defaults = {
        "category": "CLEAN",
        "source": "THREE_ONE_ONE",
    }
    defaults.update(overrides)
    return defaults
