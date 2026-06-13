"""Entity assertions and domain invariant checkers for the Earned Wage Access API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_POSTURES = {"HEALTHY", "RESTRICTED", "FROZEN"}
_PAY_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "SEMIMONTHLY"}
_TIERS = {"PROBATION", "STANDARD", "SENIOR"}
_PERIOD_STATES = {"OPEN", "LOCKED", "DISBURSED"}
_EMPLOYMENT = {"ACTIVE", "SUSPENDED", "TERMINATED"}
_ELIGIBILITY = {"ELIGIBLE", "ON_HOLD"}
_TIME_ENTRY_STATES = {"POSTED", "VOIDED"}
_ADVANCE_STATES = {
    "REQUESTED", "APPROVED", "DISBURSED", "RECOUPING",
    "SETTLED", "DEFAULTED", "DECLINED", "WRITTEN_OFF",
}
_SPEEDS = {"STANDARD", "INSTANT"}
_BATCH_STATES = {"DRAFT", "POSTED", "RECONCILED", "CANCELLED"}
_STATEMENT_STATES = {"DRAFT", "SIGNED"}
_OUTCOMES = {"CLEAN", "DISCREPANCY"}
_APPLIED_TO = {"FEE", "PRINCIPAL"}


def _assert_common(data: dict):
    """Common system fields for entities carrying id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    """Append-only entities carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not expose version"
    assert "updated_at" not in data, "append-only entity must not expose updated_at"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["pay_frequency"] in _PAY_FREQUENCIES
    assert isinstance(data["funding_balance_cents"], int)
    assert data["posture"] in _POSTURES
    assert isinstance(data["outstanding_principal_cents"], int)


def assert_advance_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert data["tier"] in _TIERS
    assert isinstance(data["min_tenure_days"], int)
    assert isinstance(data["per_advance_floor_cents"], int)
    assert isinstance(data["per_advance_ceiling_cents"], int)
    assert isinstance(data["cumulative_period_ceiling_cents"], int)
    assert data["status"] in {"ACTIVE", "ARCHIVED"}


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["expedite_flat_fee_cents"], int)
    assert isinstance(data["max_total_fee_cents"], int)
    assert isinstance(data["tip_allowed"], bool)
    assert data["status"] in {"ACTIVE", "ARCHIVED"}


def assert_pay_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["period_index"], int)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["gross_accrued_cents"], int)
    assert data["status"] in _PERIOD_STATES


def assert_worker(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["external_payroll_ref"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["tenure_days"], int)
    assert data["employment_status"] in _EMPLOYMENT
    assert data["advance_eligibility"] in _ELIGIBILITY
    assert isinstance(data["period_advance_count"], int)
    assert isinstance(data["net_available_earnings_cents"], int)
    assert isinstance(data["lifetime_advanced_cents"], int)


def assert_time_entry(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data["pay_period_id"])
    assert is_valid_uuid(data["worker_id"])
    assert isinstance(data["gross_earned_cents"], int)
    assert data["status"] in _TIME_ENTRY_STATES


def assert_advance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert is_valid_uuid(data["worker_id"])
    assert is_valid_uuid(data["pay_period_id"])
    assert isinstance(data["requested_principal_cents"], int)
    assert data["disbursement_speed"] in _SPEEDS
    assert isinstance(data["tip_cents"], int)
    assert data["status"] in _ADVANCE_STATES


def assert_repayment_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pay_period_id"])
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["total_recouped_cents"], int)
    assert isinstance(data["advance_count"], int)
    assert data["status"] in _BATCH_STATES


def assert_repayment(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data["advance_id"])
    assert is_valid_uuid(data["repayment_batch_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["applied_to"] in _APPLIED_TO


def assert_reconciliation_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pay_period_id"])
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["expected_recoup_cents"], int)
    assert isinstance(data["actual_recouped_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["drift_cents"], int)
    assert data["outcome"] in _OUTCOMES
    assert data["status"] in _STATEMENT_STATES
