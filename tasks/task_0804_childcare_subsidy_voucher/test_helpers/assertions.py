"""Entity assertions — shape/type checks for each CCDF resource.

These verify field presence and types described in the PRD (§2.4, §3). They do
NOT assert absolute version numbers, which the PRD does not pin to a specific
starting value.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_mutable(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_family(data: dict):
    _common_mutable(data)
    assert isinstance(data["applicant_name"], str) and data["applicant_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["monthly_gross_income_cents"], int) and data["monthly_gross_income_cents"] >= 0
    assert isinstance(data["monthly_self_employment_income_cents"], int)
    assert data["status"] in ["PENDING", "ELIGIBLE", "INELIGIBLE", "CLOSED"]
    assert isinstance(data["total_copay_charged_cents"], int)
    assert "active_authorization_id" in data


def assert_parent_activity(data: dict):
    _common(data)
    assert data["activity_type"] in ["WORK", "EDUCATION", "JOB_SEARCH"]
    assert isinstance(data["weekly_hours"], int) and data["weekly_hours"] >= 0


def assert_income_standard(data: dict):
    _common(data)
    assert isinstance(data["entry_monthly_limit_cents"], int)
    assert isinstance(data["exit_monthly_limit_cents"], int)


def assert_determination(data: dict):
    _common_mutable(data)
    assert data["determination_type"] in ["INITIAL", "REDETERMINATION"]
    assert isinstance(data["countable_income_cents"], int)
    assert isinstance(data["income_eligible"], bool)
    assert isinstance(data["activity_eligible"], bool)
    assert data["result"] in [None, "APPROVED", "DENIED"]
    assert isinstance(data["monthly_copay_cents"], int)
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "EXPIRED"]


def assert_provider(data: dict):
    _common_mutable(data)
    assert data["provider_type"] in ["CENTER", "FAMILY_HOME"]
    assert isinstance(data["published_daily_rate_cents"], int) and data["published_daily_rate_cents"] >= 0
    assert data["license_status"] in [
        "PENDING_VERIFICATION", "LICENSED", "REJECTED", "EXPIRED", "REVOKED"
    ]
    assert isinstance(data["total_net_paid_cents"], int)


def assert_rate_ceiling(data: dict):
    _common(data)
    assert data["provider_type"] in ["CENTER", "FAMILY_HOME"]
    assert data["care_level"] in ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]
    assert isinstance(data["max_daily_rate_cents"], int)


def assert_authorization(data: dict):
    _common_mutable(data)
    assert data["care_level"] in ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]
    assert isinstance(data["authorized_days_per_month"], int) and data["authorized_days_per_month"] >= 1
    assert isinstance(data["authorized_daily_rate_cents"], int)
    assert isinstance(data["monthly_copay_cents"], int)
    assert isinstance(data["estimated_monthly_payment_cents"], int)
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED"]


def assert_attendance_record(data: dict):
    _common_mutable(data)
    assert isinstance(data["present_days"], int) and data["present_days"] >= 0
    assert isinstance(data["absent_days"], int) and data["absent_days"] >= 0
    assert isinstance(data["payable_days"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED"]


def assert_payment(data: dict):
    _common_mutable(data)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["copay_deducted_cents"], int)
    assert isinstance(data["net_provider_payment_cents"], int)
    assert data["net_provider_payment_cents"] >= 0, "net payment is floored at 0"
    assert data["status"] in ["PAID", "REVERSED"]


def assert_overpayment_claim(data: dict):
    _common_mutable(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["recovered_amount_cents"], int)
    assert data["reason"] in ["PAYMENT_REVERSAL", "LICENSE_REVOKED", "INELIGIBLE_PERIOD"]
    assert data["status"] in ["OPEN", "RECOVERING", "RECOVERED", "WAIVED"]
