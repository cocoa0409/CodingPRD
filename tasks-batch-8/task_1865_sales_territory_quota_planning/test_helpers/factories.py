"""Payload factories — one per resource, input fields only."""
from .constants import (
    DEFAULT_LOCK_DATE,
    DEFAULT_PLAN_END,
    DEFAULT_PLAN_START,
    STANDARD_RAMP_MULTIPLIERS,
    TEST_DEFAULTS,
)

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_plan_year_payload(**overrides) -> dict:
    defaults = {
        "label": f"FY27-{_seq()}",
        "start_date": DEFAULT_PLAN_START,
        "end_date": DEFAULT_PLAN_END,
        "company_target_cents": TEST_DEFAULTS["COMPANY_TARGET_CENTS"],
        "productivity_per_rep_cents": TEST_DEFAULTS["PRODUCTIVITY_PER_REP_CENTS"],
        "lock_date": DEFAULT_LOCK_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(plan_year_id, **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "name": f"T-{_seq()}",
        "potential_cents": TEST_DEFAULTS["TERRITORY_POTENTIAL_CENTS"],
        "headcount_capacity": TEST_DEFAULTS["TERRITORY_HEADCOUNT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_geo_rule_payload(plan_year_id, territory_id, **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "rule_type": "GEO_SEGMENT",
        "priority": 10,
        "territory_id": territory_id,
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_named_rule_payload(plan_year_id, territory_id, named_account_id,
                              **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "rule_type": "NAMED_ACCOUNT",
        "priority": 5,
        "territory_id": territory_id,
        "named_account_id": named_account_id,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(plan_year_id, **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "name": f"ACC-{_seq()}",
        "country_code": "US",
        "segment": "SMB",
        "annual_potential_cents": TEST_DEFAULTS["ACCOUNT_ANNUAL_POTENTIAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rep_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Rep {n}",
        "email": f"rep{n}@example.com",
        "hire_date": TEST_DEFAULTS["VETERAN_HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_ramp_schedule_payload(**overrides) -> dict:
    defaults = {
        "name": f"Ramp-{_seq()}",
        "multipliers": list(STANDARD_RAMP_MULTIPLIERS),
    }
    defaults.update(overrides)
    return defaults


def create_rep_assignment_payload(plan_year_id, rep_id, territory_id,
                                  **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "rep_id": rep_id,
        "territory_id": territory_id,
        "effective_from": DEFAULT_PLAN_START,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(plan_year_id, scope_territory_id, pool_cents,
                              **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "scope_territory_id": scope_territory_id,
        "pool_cents": pool_cents,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(plan_year_id, territory_id, proposed_quota_cents,
                              **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "territory_id": territory_id,
        "proposed_quota_cents": proposed_quota_cents,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_run_payload(plan_year_id, **overrides) -> dict:
    defaults = {"plan_year_id": plan_year_id}
    defaults.update(overrides)
    return defaults


def create_change_request_payload(plan_year_id, account_id, from_territory_id,
                                  to_territory_id, effective_date,
                                  **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "account_id": account_id,
        "from_territory_id": from_territory_id,
        "to_territory_id": to_territory_id,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_credit_event_payload(plan_year_id, account_id, amount_cents,
                                booking_date, **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "account_id": account_id,
        "amount_cents": amount_cents,
        "booking_date": booking_date,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(plan_year_id, account_id, claimant_territory_id,
                           **overrides) -> dict:
    defaults = {
        "plan_year_id": plan_year_id,
        "account_id": account_id,
        "claimant_territory_id": claimant_territory_id,
        "reason": "account belongs to my territory",
    }
    defaults.update(overrides)
    return defaults
