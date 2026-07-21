"""Payload factories — one per entity, input fields only (PRD §3)."""
import random


def _rand_ein() -> str:
    """A unique 9-digit EIN. Each test runs against a fresh DB, but a single
    test may create several clients that must not collide on EIN."""
    return "".join(str(random.randint(0, 9)) for _ in range(9))


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer Co",
        "ein": _rand_ein(),
        "industry": "TECH",
        "fiscal_year_end_month": 12,
    }
    defaults.update(overrides)
    return defaults


def create_census_member_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "full_name": "Test Member",
        "birth_date": "1990-01-01",
        "annual_salary_cents": 5_000_000,
        "monthly_contribution_cents": 20_000,
        "employment_type": "FULL_TIME",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "coverage_line": "MEDICAL",
        "target_effective_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "carrier_name": "Acme Health",
        "monthly_premium_cents": 500_000,
        "commission_rate_pct": 0.04,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(client_id, quote_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "quote_id": quote_id,
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_payload(policy_id, expected_policy_version, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "expected_policy_version": expected_policy_version,
        "initial_offer_premium_cents": 900_000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_window_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "plan_year": 2026,
        "opens_at": "2026-07-01T00:00:00Z",
        "closes_at": "2026-07-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(window_id, census_member_id, policy_id, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "census_member_id": census_member_id,
        "policy_id": policy_id,
        "coverage_tier": "EMPLOYEE_ONLY",
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "filing_type": "ACA_1094C",
        "plan_year": 2026,
        "due_date": "2027-03-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_stop_loss_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "attachment_point_cents": 5_000_000,
        "aggregate_limit_cents": 50_000_000,
        "wellness_credit_pct": 0.05,
    }
    defaults.update(overrides)
    return defaults
