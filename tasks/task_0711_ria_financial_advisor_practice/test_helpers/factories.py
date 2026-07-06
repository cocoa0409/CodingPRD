"""Payload factories — one per entity, input fields only (RIA Practice PRD §3)."""
from .constants import (
    STANDARD_TIERS, STANDARD_MINIMUM_ANNUAL_FEE_CENTS, FLAT_TIERS,
)


def fee_schedule_payload(**overrides) -> dict:
    """POST /fee-schedules input. Defaults to the standard three-tier schedule."""
    defaults = {
        "name": "Standard 2024",
        "tiers": [dict(t) for t in STANDARD_TIERS],
        "minimum_annual_fee_cents": STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def flat_fee_schedule_payload(**overrides) -> dict:
    """A single open-ended flat tier where the fee amount is incidental."""
    defaults = {
        "name": "Flat",
        "tiers": [dict(t) for t in FLAT_TIERS],
        "minimum_annual_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def household_payload(fee_schedule_id, **overrides) -> dict:
    """POST /households input."""
    defaults = {
        "name": "The Carter Family",
        "lead_advisor_id": "adv-1",
        "fee_schedule_id": fee_schedule_id,
    }
    defaults.update(overrides)
    return defaults


def client_payload(household_id, **overrides) -> dict:
    """POST /clients input. All listed fields are required (no defaults)."""
    defaults = {
        "household_id": household_id,
        "full_name": "Jane Carter",
        "date_of_birth": "1980-01-01",
        "risk_capacity_score": 60,
        "risk_tolerance_score": 60,
    }
    defaults.update(overrides)
    return defaults


def portfolio_payload(**overrides) -> dict:
    """POST /portfolios input. target_weights sum to 100."""
    defaults = {
        "name": "Balanced Growth",
        "model_equity_pct": 60,
        "target_weights": [
            {"sleeve": "EQ", "target_pct": 60},
            {"sleeve": "FI", "target_pct": 40},
        ],
    }
    defaults.update(overrides)
    return defaults


def ips_payload(client_id, target_portfolio_id, **overrides) -> dict:
    """POST /investment-policy-statements input. drift_tolerance_bps optional."""
    defaults = {
        "client_id": client_id,
        "target_portfolio_id": target_portfolio_id,
        "max_equity_pct": 80,
        "drift_tolerance_bps": 500,
    }
    defaults.update(overrides)
    return defaults


def account_payload(household_id, client_id, **overrides) -> dict:
    """POST /accounts input. held_away/billable/market/equity have defaults."""
    defaults = {
        "household_id": household_id,
        "client_id": client_id,
        "custodian": "Schwab",
        "account_type": "TAXABLE",
        "market_value_cents": 0,
        "equity_value_cents": 0,
        "billable": True,
        "held_away": False,
    }
    defaults.update(overrides)
    return defaults


def fee_run_payload(household_id, expected_household_version, **overrides) -> dict:
    """POST /fee-runs input. expected_household_version is mandatory (PRD §2.6)."""
    defaults = {
        "household_id": household_id,
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults


def financial_plan_payload(household_id, **overrides) -> dict:
    """POST /financial-plans input. return/contribution have defaults."""
    defaults = {
        "household_id": household_id,
        "name": "Retirement 2045",
        "assumed_annual_return_bps": 600,
        "monthly_contribution_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def goal_payload(plan_id, **overrides) -> dict:
    """POST /goals input. current_amount_cents and priority have defaults."""
    defaults = {
        "plan_id": plan_id,
        "name": "College Fund",
        "target_amount_cents": 1000000,
        "target_date": "2030-01-01",
        "current_amount_cents": 0,
        "priority": "SECONDARY",
    }
    defaults.update(overrides)
    return defaults


def review_payload(household_id, **overrides) -> dict:
    """POST /reviews input. cadence_days optional (defaults to 365)."""
    defaults = {
        "household_id": household_id,
        "scheduled_for": "2026-09-01",
        "cadence_days": 365,
    }
    defaults.update(overrides)
    return defaults


def compliance_item_payload(subject_type, subject_id, **overrides) -> dict:
    """POST /compliance-items input."""
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "obligation_type": "REG_BI_DISCLOSURE",
        "due_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults
