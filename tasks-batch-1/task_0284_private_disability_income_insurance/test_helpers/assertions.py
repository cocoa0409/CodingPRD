"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates structural shape (ids, timestamps, enum domains,
field types). Field names mirror the PRD exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CLAIM_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PENDING_INFO", "APPROVED",
    "SUSPENDED", "DENIED", "CLOSED", "BENEFIT_EXHAUSTED",
}
_LIFECYCLE_STATUSES = {"PENDING", "ACTIVE", "LAPSED", "TERMINATED"}
_PREMIUM_STATUSES = {"CURRENT", "GRACE", "DEFAULT"}
_RISK_TIERS = {"LOW", "MEDIUM", "HIGH", "DECLINE"}
_OCC_DEFS = {"OWN_OCC", "ANY_OCC"}
_DISABILITY_TYPES = {"TOTAL", "RESIDUAL"}
_BP_STATUSES = {"ACCRUED", "REVERSED"}
_OFFSET_SOURCES = {"SSDI", "WORKERS_COMP"}
_OFFSET_STATUSES = {"ESTIMATED", "FINALIZED", "VOID"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_insurer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_month_index"], int)
    assert data["current_month_index"] >= 0


def assert_occupation_class(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["insurer_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["risk_tier"] in _RISK_TIERS
    assert isinstance(data["max_benefit_months"], int)
    assert isinstance(data["min_elimination_days"], int)
    assert isinstance(data["own_occ_window_months_cap"], int)


def assert_policyholder(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["insurer_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["pre_disability_monthly_income_cents"], int)
    assert data["pre_disability_monthly_income_cents"] > 0


def assert_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["insurer_id"])
    assert is_valid_uuid(data["policyholder_id"])
    assert is_valid_uuid(data["occupation_class_id"])
    assert isinstance(data["monthly_benefit_cents"], int) and data["monthly_benefit_cents"] > 0
    assert isinstance(data["benefit_period_months"], int)
    assert isinstance(data["elimination_period_days"], int)
    assert data["occupation_definition"] in _OCC_DEFS
    assert data["lifecycle_status"] in _LIFECYCLE_STATUSES
    assert data["premium_status"] in _PREMIUM_STATUSES
    assert isinstance(data["benefit_months_consumed"], (int, float))
    assert data["benefit_months_consumed"] >= 0


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["insurer_id"])
    assert is_valid_uuid(data["policy_id"])
    assert isinstance(data["disability_onset_month"], int)
    assert data["claimed_disability_type"] in _DISABILITY_TYPES
    assert isinstance(data["elimination_satisfied_month"], int)
    assert isinstance(data["own_occ_expiry_month"], int)
    assert isinstance(data["next_proof_due_month"], int)
    assert data["status"] in _CLAIM_STATUSES


def assert_income_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["effective_month"], int)
    assert isinstance(data["current_monthly_income_cents"], int)
    assert isinstance(data["income_loss_ratio"], (int, float))
    assert isinstance(data["is_superseded"], bool)


def assert_disability_proof(data: dict):
    """Append-only / immutable: id + created_at only (PRD §2.5).
    No updated_at, no version on this entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["attestation_month"], int)
    assert isinstance(data["still_disabled"], bool)
    assert isinstance(data["accepted"], bool)


def assert_benefit_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["policy_id"])
    assert isinstance(data["coverage_month"], int)
    assert isinstance(data["benefit_fraction"], (int, float))
    assert isinstance(data["gross_benefit_cents"], int)
    assert isinstance(data["offset_applied_cents"], int)
    assert isinstance(data["net_benefit_cents"], int)
    assert data["net_benefit_cents"] >= 0, "net_benefit_cents floored at 0"
    assert data["status"] in _BP_STATUSES


def assert_offset_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["offset_source"] in _OFFSET_SOURCES
    assert isinstance(data["start_month"], int)
    assert isinstance(data["end_month"], int)
    assert data["end_month"] >= data["start_month"]
    assert data["status"] in _OFFSET_STATUSES


def assert_claim_ledger(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["total_gross_paid_cents"], int)
    assert isinstance(data["total_net_paid_cents"], int)
    assert isinstance(data["overpayment_balance_cents"], int)
