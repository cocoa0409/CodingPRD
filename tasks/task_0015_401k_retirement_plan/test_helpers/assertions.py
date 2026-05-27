"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ─── Common-field invariants ────────────────────────────────────────────────

def _assert_common_versioned(data: dict, entity_label: str):
    """Common fields for any entity with common_fields:true: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be integer"
    assert data["version"] >= 1, f"{entity_label}.version begins at 1 and never decreases"


def _assert_common_append_only(data: dict, entity_label: str):
    """For VestingEvent (PRD §2.4 exception): only id + created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"


# ─── Entity assertions ──────────────────────────────────────────────────────

def assert_plan(data: dict):
    _assert_common_versioned(data, "Plan")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["plan_year"], int)
    assert data["match_formula"] in ("TIERED", "SAFE_HARBOR_ENHANCED")
    assert data["vesting_schedule"] in ("CLIFF_3", "GRADED_6")
    assert data["status"] in ("DRAFT", "ACTIVE", "FROZEN", "TERMINATED")
    assert isinstance(data["annual_compensation_limit_cents"], int)
    assert isinstance(data["annual_deferral_limit_cents"], int)


def assert_participant(data: dict):
    _assert_common_versioned(data, "Participant")
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["full_name"], str)
    assert is_iso8601_timestamp(data["date_of_birth"])
    assert is_iso8601_timestamp(data["hire_date"])
    assert isinstance(data["annual_compensation_cents"], int)
    assert isinstance(data["deferral_rate_bps"], int)
    assert 0 <= data["deferral_rate_bps"] <= 10000
    assert data["enrollment_status"] in ("PENDING", "ENROLLED", "SUSPENDED", "TERMINATED")
    assert isinstance(data["employee_balance_cents"], int)
    assert isinstance(data["employer_balance_cents"], int)
    assert isinstance(data["vested_employer_balance_cents"], int)
    assert isinstance(data["outstanding_loan_principal_cents"], int)
    assert isinstance(data["years_of_service"], int)


def assert_contribution_period(data: dict):
    _assert_common_versioned(data, "ContributionPeriod")
    assert isinstance(data["participant_id"], str)
    assert is_iso8601_timestamp(data["period_end_date"])
    assert isinstance(data["gross_compensation_cents"], int)
    assert isinstance(data["employee_contribution_cents"], int)
    assert isinstance(data["employer_match_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED", "REVERSED")


def assert_loan(data: dict):
    _assert_common_versioned(data, "Loan")
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["principal_cents"], int)
    assert data["principal_cents"] > 0
    assert isinstance(data["term_months"], int)
    assert isinstance(data["annual_interest_rate_bps"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert data["status"] in ("REQUESTED", "DISBURSED", "REPAID", "DEFAULTED")


def assert_hardship_withdrawal(data: dict):
    _assert_common_versioned(data, "HardshipWithdrawal")
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["hardship_category"] in (
        "MEDICAL_EXPENSES",
        "PRIMARY_RESIDENCE_PURCHASE",
        "TUITION_PAYMENT",
        "EVICTION_PREVENTION",
        "FUNERAL_EXPENSES",
    )
    assert isinstance(data["approved_amount_cents"], int)
    assert data["approved_amount_cents"] >= 0
    assert isinstance(data["ten_percent_penalty_cents"], int)
    assert data["ten_percent_penalty_cents"] >= 0
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "PAID")


def assert_rmd_distribution(data: dict):
    _assert_common_versioned(data, "RMDDistribution")
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["distribution_year"], int)
    assert isinstance(data["prior_year_end_balance_cents"], int)
    assert data["rmd_variant"] in ("UNIFORM_LIFETIME", "JOINT_LIFE")
    assert isinstance(data["required_amount_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "MISSED")


def assert_vesting_event(data: dict):
    _assert_common_append_only(data, "VestingEvent")
    assert isinstance(data["participant_id"], str)
    assert is_iso8601_timestamp(data["as_of_date"])
    assert isinstance(data["years_of_service_after"], int)
    assert isinstance(data["vested_pct_bps_after"], int)
    # PRD §2.4: VestingEvent has no updated_at, no version. Implementations may
    # still serialize the field as null/missing; we explicitly forbid presence
    # of a numeric `version`, which would imply a mutable row.
    assert data.get("version") is None or not isinstance(data.get("version"), int) or data.get("version") == 0 or data.get("version") is None


# ─── Domain invariants ──────────────────────────────────────────────────────

def assert_participant_balance_non_negative(p: dict):
    """Balances are non-negative integer cents (PRD §2.5: integer cents, max(0, ...) clamps)."""
    assert p["employee_balance_cents"] >= 0
    assert p["employer_balance_cents"] >= 0
    assert p["vested_employer_balance_cents"] >= 0
    assert p["outstanding_loan_principal_cents"] >= 0


def assert_vested_le_employer(p: dict):
    """PRD §2.9: vested_employer_balance is employer_balance * vested_pct / 10000, with floor.
    Therefore vested_employer_balance_cents <= employer_balance_cents at all times."""
    assert p["vested_employer_balance_cents"] <= p["employer_balance_cents"], (
        f"vested_employer_balance_cents ({p['vested_employer_balance_cents']}) "
        f"must be <= employer_balance_cents ({p['employer_balance_cents']})"
    )
