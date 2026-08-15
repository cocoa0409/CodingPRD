"""Payload factories — input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": _uniq("Fund"),
        "fund_type": "DESIGNATED",
        "endowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "spending_rate_pct": 4.5,
        "spending_formula": "AVERAGE_12Q",
        "fee_tier_schedule": "STANDARD",
        "min_initial_contribution": 10000.00,
    }
    defaults.update(overrides)
    return defaults


def create_advisor_payload(**overrides) -> dict:
    defaults = {
        "advisor_name": _uniq("Advisor"),
        "email": f"{_uniq('advisor')}@example.org",
        "advisor_kind": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    defaults = {
        "donor_name": _uniq("Donor"),
        "asset_kind": "CASH",
        "declared_value": 50000.00,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "description": _uniq("Lot"),
        "quantity": 100,
        "appraised_value": 10000.00,
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(**overrides) -> dict:
    defaults = {
        "pool_name": _uniq("Pool"),
        "pool_kind": "BALANCED",
        "initial_nav": 1000000.00,
        "initial_units": 50000.0000,
    }
    defaults.update(overrides)
    return defaults


def create_grantee_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("Org"),
        "tax_id": f"{next(_counter) % 1000000000:09d}",
        "irs_subsection": "C3_501",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    defaults = {
        "amount": 1000.00,
        "purpose": "Charitable purpose",
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {
        "snapshot_kind": "QUARTER_END",
        "effective_date": "2025-12-31T00:00:00Z",
        "market_value": 100000.00,
    }
    defaults.update(overrides)
    return defaults


def create_fee_assessment_payload(**overrides) -> dict:
    defaults = {
        "quarter_end_date": "2026-03-31T00:00:00Z",
        "quarter_end_balance": 250000.00,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": _uniq("Program"),
        "application_open": "2026-02-01T00:00:00Z",
        "application_close": "2026-03-01T00:00:00Z",
        "award_amount": 2500.00,
        "max_awards": 1,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "member_name": _uniq("Member"),
        "email": f"{_uniq('member')}@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "applicant_name": _uniq("Applicant"),
        "applicant_email": f"{_uniq('applicant')}@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(**overrides) -> dict:
    defaults = {
        "academic": 80,
        "financial_need": 80,
        "essay": 80,
        "interview": 80,
    }
    defaults.update(overrides)
    return defaults
