"""Entity assertions and domain invariant checkers for the Pension DB Administration API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --- Entity shape assertions -------------------------------------------------
def assert_common_fields(data: dict):
    """id (UUID, no prefix), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_append_only_fields(data: dict):
    """Append-only entities carry ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_pension_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["plan_name"], str) and len(data["plan_name"]) > 0
    assert isinstance(data["ein_psn"], str) and len(data["ein_psn"]) > 0
    assert data["benefit_formula_type"] in ("FINAL_AVERAGE_PAY", "CASH_BALANCE")
    assert data["funding_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["status"] in ("ACTIVE", "TERMINATING")
    assert isinstance(data["version"], int)


def assert_participant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["ssn_last4"], str)
    assert data["employment_status"] in ("ACTIVE", "TERMINATED", "RETIRED", "DECEASED")
    assert data["vesting_status"] in ("UNVESTED", "PARTIALLY_VESTED", "FULLY_VESTED")


def assert_annual_compensation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["gross_comp_cents"], int)
    assert isinstance(data["capped_comp_cents"], int)


def assert_service_credit_adjustment(data: dict):
    assert_append_only_fields(data)
    assert "updated_at" not in data, "ServiceCreditAdjustment is append-only: no updated_at"
    assert "version" not in data, "ServiceCreditAdjustment is append-only: no version"
    assert data["adjustment_kind"] in (
        "MILITARY_BUYBACK",
        "BREAK_IN_SERVICE",
        "PRIOR_SERVICE_GRANT",
    )


def assert_plan_year_filing(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "CERTIFIED", "SUPERSEDED")
    assert isinstance(data["plan_assets_cents"], int)
    assert isinstance(data["funding_target_cents"], int)


def assert_pbgc_premium_filing(data: dict):
    assert_common_fields(data)
    assert isinstance(data["flat_rate_premium_cents"], int)
    assert isinstance(data["variable_rate_premium_cents"], int)
    assert isinstance(data["total_premium_cents"], int)


def assert_benefit_election(data: dict):
    assert_common_fields(data)
    assert data["payment_form"] in ("SINGLE_LIFE", "JOINT_AND_SURVIVOR", "LUMP_SUM")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "SPOUSAL_CONSENT_PENDING",
        "APPROVED",
        "COMMENCED",
        "REJECTED",
    )


def assert_qdro_award(data: dict):
    assert_common_fields(data)
    assert data["alternate_payee_kind"] in ("SPOUSE", "FORMER_SPOUSE", "CHILD")
    assert data["split_method"] in ("PERCENTAGE", "SHARED_INTEREST")
    assert data["status"] in ("DRAFT", "SUBMITTED", "QUALIFIED", "REJECTED")


def assert_benefit_payment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING_SETUP", "IN_PAY", "SUSPENDED", "TERMINATED")
    assert isinstance(data["base_monthly_cents"], int)
    assert isinstance(data["current_monthly_cents"], int)
    assert isinstance(data["cola_applied_count"], int)


def assert_spousal_consent(data: dict):
    assert_append_only_fields(data)
    assert "updated_at" not in data, "SpousalConsent is immutable: no updated_at"
    assert "version" not in data, "SpousalConsent is immutable: no version"
    assert isinstance(data["waives_qjsa"], bool)


# --- Domain invariant checkers ----------------------------------------------
def assert_qdro_conservation(base_monthly_cents: int, carve_cents: int, js_reduced_monthly_cents: int):
    """PRD §3.5: base_monthly_cents = js_reduced minus QUALIFIED carve-outs.

    For a single QUALIFIED award, participant net + alternate-payee carve must
    reconstitute the pre-split js_reduced amount with no drift.
    """
    assert base_monthly_cents + carve_cents == js_reduced_monthly_cents, (
        f"conservation violated: base {base_monthly_cents} + carve {carve_cents} "
        f"!= js_reduced {js_reduced_monthly_cents}"
    )
