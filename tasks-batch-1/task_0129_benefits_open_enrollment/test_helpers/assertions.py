"""Entity assertions and domain invariant checkers for the Benefits Open Enrollment API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version present (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_common_ledger(data: dict):
    """Immutable ledger event: only id + created_at; no updated_at / version (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_employee(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["employment_type"] in ("FULL_TIME", "PART_TIME", "SEASONAL")
    assert data["payroll_schedule"] in ("SEMI_MONTHLY", "BIWEEKLY")
    assert isinstance(data["monthly_household_income_cents"], int)
    assert data["eligibility_status"] in ("WAITING", "ELIGIBLE", "INELIGIBLE", "TERMINATED")
    assert isinstance(data["pay_periods_processed"], int)


def assert_waiting_period(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["window_type"] in ("INITIAL", "REINSTATEMENT")
    assert data["status"] in ("PENDING", "ELAPSED")


def assert_plan_offering(data: dict):
    _assert_common_mutable(data)
    assert data["benefit_type"] in ("MEDICAL", "DENTAL", "VISION", "VOLUNTARY_LIFE")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_plan_tier(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["plan_offering_id"])
    assert data["coverage_level"] in (
        "EMPLOYEE_ONLY", "EMPLOYEE_PLUS_SPOUSE",
        "EMPLOYEE_PLUS_CHILDREN", "EMPLOYEE_PLUS_FAMILY",
    )
    assert isinstance(data["monthly_premium_cents"], int)
    assert 0.0 <= data["employer_contribution_pct"] <= 1.0


def assert_dependent(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["relationship"] in ("SPOUSE", "CHILD")
    assert data["verification_status"] in ("PENDING", "INFO_REQUESTED", "VERIFIED", "REJECTED")


def assert_enrollment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["plan_tier_id"])
    assert data["benefit_type"] in ("MEDICAL", "DENTAL", "VISION", "VOLUNTARY_LIFE")
    assert data["status"] in ("DRAFT", "PENDING_EOI", "ACTIVE", "SUPERSEDED", "CANCELLED")
    assert isinstance(data["covered_dependent_count"], int)


def assert_life_event(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["event_type"] in ("BIRTH", "MARRIAGE", "DIVORCE", "LOSS_OF_COVERAGE")
    assert data["adjustment_mode"] in ("PROSPECTIVE", "RETROACTIVE")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_eoi_request(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["decision"] in ("PENDING", "APPROVED", "DENIED")


def assert_form_1095c(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["tax_year"], int)
    assert data["affordability_indicator"] in ("AFFORDABLE", "UNAFFORDABLE")
    assert data["status"] in ("GENERATED", "FILED")


def assert_deduction_line(data: dict):
    _assert_common_ledger(data)
    assert "updated_at" not in data, "DeductionLine is an immutable ledger event and must not carry updated_at"
    assert "version" not in data, "DeductionLine is an immutable ledger event and must not carry version"
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["pay_period_index"], int)
    assert data["line_type"] in ("REGULAR", "RETRO_ADJUSTMENT")
    assert isinstance(data["amount_cents"], int)


def assert_carrier_feed_record(data: dict):
    _assert_common_ledger(data)
    assert "updated_at" not in data, "CarrierFeedRecord is an immutable ledger event and must not carry updated_at"
    assert "version" not in data, "CarrierFeedRecord is an immutable ledger event and must not carry version"
    assert is_valid_uuid(data["enrollment_id"])
    assert data["transaction_set"] in ("ADD", "TERM", "CHANGE")
    assert isinstance(data["reconciled_monthly_premium_cents"], int)
