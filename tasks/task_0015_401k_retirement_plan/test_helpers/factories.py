"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


# ─── Plan ───────────────────────────────────────────────────────────────────

def create_plan_payload(**overrides) -> dict:
    """PRD §3.1: name, plan_year (1900..2999), match_formula, vesting_schedule;
    annual_compensation_limit_cents and annual_deferral_limit_cents are optional."""
    defaults = {
        "name": "Test Plan",
        "plan_year": 2026,
        "match_formula": "TIERED",
        "vesting_schedule": "GRADED_6",
    }
    defaults.update(overrides)
    return defaults


def terminate_plan_payload(expected_plan_version: int) -> dict:
    """PRD §2.7: terminate body must include expected_plan_version."""
    return {"expected_plan_version": expected_plan_version}


# ─── Participant ────────────────────────────────────────────────────────────

def create_participant_payload(plan_id: str, **overrides) -> dict:
    """PRD §3.2 — plan_id, full_name, date_of_birth, hire_date, annual_compensation_cents
    (>0), and optional deferral_rate_bps in [0, 10000]."""
    defaults = {
        "plan_id": plan_id,
        "full_name": "Test Participant",
        "date_of_birth": "1980-06-15T00:00:00Z",
        "hire_date": "2024-06-15T00:00:00Z",
        "annual_compensation_cents": 12_000_000,
        "deferral_rate_bps": 400,
    }
    defaults.update(overrides)
    return defaults


def deferral_rate_payload(deferral_rate_bps: int) -> dict:
    return {"deferral_rate_bps": deferral_rate_bps}


# ─── ContributionPeriod ─────────────────────────────────────────────────────

def create_contribution_period_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "period_end_date": "2026-06-15T00:00:00Z",
        "gross_compensation_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


# ─── Loan ───────────────────────────────────────────────────────────────────

def create_loan_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "principal_cents": 10_000,
        "term_months": 12,
        "annual_interest_rate_bps": 700,
    }
    defaults.update(overrides)
    return defaults


def repay_loan_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


# ─── HardshipWithdrawal ─────────────────────────────────────────────────────

def create_hardship_withdrawal_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "requested_amount_cents": 100_000,
        "hardship_category": "MEDICAL_EXPENSES",
    }
    defaults.update(overrides)
    return defaults


# ─── RMDDistribution ────────────────────────────────────────────────────────

def create_rmd_distribution_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "distribution_year": 2026,
        "prior_year_end_balance_cents": 1_000_000,
        "rmd_variant": "UNIFORM_LIFETIME",
    }
    defaults.update(overrides)
    return defaults


def pay_rmd_payload(distributed_amount_cents: int) -> dict:
    return {"distributed_amount_cents": distributed_amount_cents}


# ─── VestingEvent ───────────────────────────────────────────────────────────

def create_vesting_event_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "as_of_date": "2026-06-15T00:00:00Z",
        "years_of_service_after": 2,
        "vested_pct_bps_after": 4000,
    }
    defaults.update(overrides)
    return defaults


# ─── Test-driving (PRD §3.8) ────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def year_tick_payload(as_of_year: int) -> dict:
    return {"as_of_year": as_of_year}
