"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["ein"], str)
    assert data["industry"] in ["RETAIL", "MANUFACTURING", "TECH", "HEALTHCARE", "OTHER"]
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert isinstance(data["employee_count"], int)
    assert isinstance(data["full_time_equivalent_count"], int)
    assert isinstance(data["is_ale"], bool)
    assert isinstance(data["enrolled_headcount"], int)
    assert isinstance(data["active_premium_total_cents"], int)
    assert isinstance(data["ytd_commission_cents"], int)


def assert_census_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["employment_type"] in ["FULL_TIME", "PART_TIME"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["affordable_rate_of_pay"], bool)
    assert isinstance(data["affordable_fpl"], bool)


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["coverage_line"] in ["MEDICAL", "DENTAL", "VISION", "LIFE"]
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED"]


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_premium_cents"], int) and data["monthly_premium_cents"] >= 1
    assert 0 <= data["commission_rate_pct"] <= 1
    assert data["status"] in ["SUBMITTED", "SELECTED", "DECLINED"]


def assert_policy(data: dict):
    _assert_common(data)
    assert data["coverage_line"] in ["MEDICAL", "DENTAL", "VISION", "LIFE"]
    assert isinstance(data["original_premium_cents"], int)
    assert isinstance(data["monthly_premium_cents"], int)
    assert isinstance(data["estimated_commission_cents"], int)
    assert isinstance(data["finalized_commission_cents"], int)
    assert data["commission_status"] in ["PENDING", "FINALIZED"]
    assert data["renewal_status"] in ["NONE", "RENEWING", "RENEWED"]
    assert data["lifecycle_status"] in ["BOUND", "ACTIVE", "TERMINATED"]


def assert_renewal(data: dict):
    _assert_common(data)
    assert data["proposing_side"] in ["CARRIER", "BROKER"]
    assert isinstance(data["round_count"], int)
    assert data["status"] in ["OPEN", "NEGOTIATING", "AGREED", "DECLINED"]


def assert_enrollment_window(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_year"], int)
    assert data["status"] in ["SCHEDULED", "OPEN", "FINALIZED"]
    assert isinstance(data["total_confirmed_cents"], int)


def assert_election(data: dict):
    _assert_common(data)
    assert data["coverage_tier"] in [
        "EMPLOYEE_ONLY", "EMPLOYEE_SPOUSE", "EMPLOYEE_CHILD", "FAMILY"
    ]
    assert data["status"] in ["SELECTED", "CONFIRMED", "WAIVED", "WITHDRAWN"]


def assert_filing(data: dict):
    _assert_common(data)
    assert data["filing_type"] in ["ACA_1094C", "FORM_5500", "ERISA_SPD"]
    assert data["status"] in ["DRAFT", "PREPARED", "CERTIFIED", "FILED", "LATE"]


def assert_stop_loss_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["attachment_point_cents"], int)
    assert isinstance(data["cumulative_claims_cents"], int)
    assert isinstance(data["reimbursed_cents"], int)
    assert isinstance(data["wellness_credit_cents"], int)
    assert isinstance(data["total_recovery_cents"], int)
