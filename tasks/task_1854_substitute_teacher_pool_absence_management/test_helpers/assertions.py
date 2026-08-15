"""Entity assertions and domain invariant checkers (PRD 2.2, 2.4, 2.9, 3.6)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Primary resources carry id/created_at/updated_at/version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["offer_response_window_minutes"], int)
    assert isinstance(data["long_term_approval_days"], int)
    assert isinstance(data["long_term_threshold_days"], int)
    assert isinstance(data["premium_cap_multiplier"], (int, float))
    assert isinstance(data["suspension_score_threshold"], int)


def assert_school(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("district_id", "")), "district_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["hard_to_fill_tier"] in ["NONE", "MODERATE", "HIGH"]
    assert isinstance(data["coverage_budget_total_cents"], int)
    assert isinstance(data["coverage_budget_committed_cents"], int)
    assert isinstance(data["coverage_budget_spent_cents"], int)
    assert isinstance(data["coverage_budget_available_cents"], int)
    assert_school_budget_invariants(data)


def assert_school_budget_invariants(data: dict):
    """PRD 2.9: available == total - committed - spent and never negative."""
    total = data["coverage_budget_total_cents"]
    committed = data["coverage_budget_committed_cents"]
    spent = data["coverage_budget_spent_cents"]
    available = data["coverage_budget_available_cents"]
    assert committed >= 0, "committed must not be negative"
    assert spent >= 0, "spent must not be negative"
    assert available >= 0, "available must never go negative"
    assert available == total - committed - spent, (
        f"available {available} != total {total} - committed {committed} - spent {spent}"
    )


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("school_id", "")), "school_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["grade_band"] in ["ELEMENTARY", "MIDDLE", "HIGH"]
    assert isinstance(data["is_coordinator"], bool)


def assert_substitute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["base_daily_rate_cents"], int)
    assert data["status"] in ["PENDING_CLEARANCE", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["reliability_events"], list)
    for event in data["reliability_events"]:
        assert isinstance(event.get("event_type"), str)
        assert isinstance(event.get("delta"), int)
        assert is_iso8601_timestamp(event.get("occurred_at", ""))
    assert 0 <= data["reliability_lifetime_score"] <= 100
    assert 0 <= data["reliability_trailing_score"] <= 100
    assert data["completions_lifetime"] >= 0
    assert data["completions_trailing"] >= 0


def assert_qualification(data: dict):
    """Append-only grant record: id + created_at only (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Qualification carries no updated_at"
    assert "version" not in data, "Qualification carries no version"
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["grade_band"] in ["ELEMENTARY", "MIDDLE", "HIGH"]


def assert_clearance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert data["clearance_type"] in ["BACKGROUND_CHECK", "TEACHING_CREDENTIAL", "TB_TEST"]
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["status"] in ["PENDING", "VERIFIED", "EXPIRED"]


def assert_mark(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("school_id", ""))
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert data["mark_type"] in ["PREFERRED", "DO_NOT_RETURN"]
    assert data["status"] in ["ACTIVE", "LIFTED"]


def assert_absence(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("staff_member_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["absence_type"] in ["SICK", "PERSONAL", "PROFESSIONAL_DEVELOPMENT", "JURY_DUTY"]
    assert isinstance(data["required_subject"], str) and data["required_subject"]
    assert data["required_grade_band"] in ["ELEMENTARY", "MIDDLE", "HIGH"]
    assert isinstance(data["total_days"], int) and data["total_days"] >= 1
    assert data["fill_status"] in [
        "REPORTED", "DISPATCHING", "ASSIGNED", "COMPLETED",
        "UNFILLED", "COVERED_INTERNALLY", "CLOSED", "CANCELLED",
    ]
    assert data["approval_status"] in ["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"]
    assert_absence_day_conservation(data)


def assert_absence_day_conservation(data: dict):
    """PRD 3.6: internal + sub + uncovered days exactly equal total_days."""
    total = data["total_days"]
    internal = data["days_covered_internal"]
    sub = data["days_covered_sub"]
    uncovered = data["days_uncovered"]
    assert internal + sub + uncovered == total, (
        f"day conservation broken: {internal} + {sub} + {uncovered} != {total}"
    )
    assert 0 <= internal <= total
    assert 0 <= sub <= total
    assert 0 <= uncovered <= total


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("absence_id", ""))
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert data["offer_source"] in ["AUTO_DISPATCH", "MANUAL_OFFER", "SELF_CLAIM"]
    assert isinstance(data["offer_sequence"], int) and data["offer_sequence"] >= 1
    assert data["status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED",
        "WORKED", "NO_SHOW", "VERIFIED", "PAID",
    ]
    assert is_iso8601_timestamp(data.get("offered_at", ""))
    assert is_iso8601_timestamp(data.get("offer_expires_at", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["scheduled_days"], int) and data["scheduled_days"] >= 1
    assert isinstance(data["premium_multiplier_snapshot"], (int, float))
    assert isinstance(data["provisional_pay_cents"], int)
    assert isinstance(data["worked_days_count"], int) and data["worked_days_count"] >= 0
    assert isinstance(data["long_term_converted"], bool)
    assert isinstance(data["payout_capped"], bool)


def assert_internal_coverage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("absence_id", ""))
    assert is_valid_uuid(data.get("staff_member_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["coverage_date"], str) and data["coverage_date"]
    assert isinstance(data["periods"], int) and data["periods"] >= 1
    assert data["status"] in [
        "PROPOSED", "APPROVED", "REJECTED", "WORKED", "COMPENSATED", "CANCELLED",
    ]


def assert_timesheet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert isinstance(data["work_date"], str) and data["work_date"]
    assert isinstance(data["hours_worked"], (int, float))
    assert 0.5 <= data["hours_worked"] <= 12.0
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "EXPORTED"]


def assert_payroll_period(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert data["status"] in ["OPEN", "EXPORTED"]


def assert_performance_flag(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("substitute_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert data["flag_type"] in ["NO_SHOW", "CONDUCT", "QUALITY", "TARDINESS"]
    assert data["severity"] in ["MINOR", "MAJOR"]
    assert data["status"] in ["OPEN", "RESOLVED", "ESCALATED"]
    assert isinstance(data["auto_created"], bool)


def assert_dispatch_batch(data: dict):
    """Append-only run record: id + created_at only (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DispatchBatch carries no updated_at"
    assert "version" not in data, "DispatchBatch carries no version"
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_iso8601_timestamp(data.get("executed_at", ""))
    assert isinstance(data["absences_considered"], int)
    assert isinstance(data["offers_created"], int)
    assert isinstance(data["offers_expired"], int)
    assert isinstance(data["absences_marked_unfilled"], int)
