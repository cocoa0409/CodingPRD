"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("employee_number"), str)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("location_code"), str)
    assert isinstance(data.get("department"), str)
    assert data.get("employment_status") in ("ACTIVE", "ON_LEAVE", "TERMINATED")
    assert isinstance(data.get("hire_date"), str)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" in data


def assert_investigator(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be valid UUID"
    assert data.get("certification_level") in ("LEVEL_1", "LEVEL_2", "LEVEL_3")
    assert isinstance(data.get("max_active_cases"), int)
    assert isinstance(data.get("active_case_count"), int)
    assert isinstance(data.get("conflicted_employee_ids"), list)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" in data


def assert_intake_channel(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data.get("channel_code") in (
        "HOTLINE", "WEB_PORTAL", "MANAGER_REFERRAL", "HR_DIRECT", "ANONYMOUS_LETTER",
    )
    assert isinstance(data.get("display_name"), str)
    assert data.get("default_category") in (
        "HARASSMENT", "DISCRIMINATION", "RETALIATION", "POLICY_VIOLATION",
        "SAFETY", "COMPENSATION", "OTHER",
    )
    assert data.get("default_severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data.get("requires_reporter_identity"), bool)
    assert isinstance(data.get("sla_business_days"), int)
    assert "version" in data


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("case_number"), str)
    assert is_valid_uuid(data.get("intake_channel_id", ""))
    assert is_valid_uuid(data.get("subject_employee_id", ""))
    assert data.get("category") in (
        "HARASSMENT", "DISCRIMINATION", "RETALIATION", "POLICY_VIOLATION",
        "SAFETY", "COMPENSATION", "OTHER",
    )
    assert data.get("severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data.get("status") in (
        "TRIAGE", "ASSIGNED", "INVESTIGATING", "FINDINGS_DRAFT", "CALIBRATION",
        "PENDING_CLOSURE", "CLOSED", "REOPENED", "ON_HOLD",
    )
    assert isinstance(data.get("litigation_hold"), bool)
    assert isinstance(data.get("reopen_count"), int)
    assert is_iso8601_timestamp(data.get("intake_received_at", ""))
    assert "version" in data


def assert_interview(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("interviewee_employee_id", ""))
    assert is_valid_uuid(data.get("interviewer_investigator_id", ""))
    assert isinstance(data.get("scheduled_start"), str)
    assert isinstance(data.get("scheduled_end"), str)
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert "version" in data


def assert_evidence_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("submitted_by_employee_id", ""))
    assert data.get("evidence_type") in (
        "DOCUMENT", "EMAIL", "CHAT_LOG", "PHOTO", "AUDIO", "VIDEO",
        "PHYSICAL", "TESTIMONY",
    )
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("custody_sequence"), int)
    assert data.get("status") in ("LOGGED", "UNDER_REVIEW", "ADMITTED", "EXCLUDED", "ARCHIVED")
    assert "version" in data


def assert_credibility_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("subject_employee_id", ""))
    assert is_valid_uuid(data.get("assessor_investigator_id", ""))
    assert isinstance(data.get("corroboration_count"), int)
    assert isinstance(data.get("contradiction_count"), int)
    assert isinstance(data.get("account_age_days"), int)
    assert isinstance(data.get("score_corroboration"), (int, float))
    assert isinstance(data.get("score_recency"), (int, float))
    assert data.get("active_variant") in ("CORROBORATION_WEIGHTED", "RECENCY_WEIGHTED")
    assert "version" in data


def assert_finding(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("author_investigator_id", ""))
    assert data.get("substantiation_status") in (
        "DRAFT", "SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE",
    )
    assert data.get("approval_status") in (
        "PENDING_REVIEW", "CALIBRATED", "REJECTED", "APPROVED",
    )
    assert isinstance(data.get("rationale_text"), str)
    assert isinstance(data.get("calibrated_by_ids"), list)
    assert "version" in data


def assert_recommended_action(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("finding_id", ""))
    assert data.get("action_type") in (
        "NO_ACTION", "COACHING", "WRITTEN_WARNING", "FINAL_WARNING",
        "SUSPENSION", "DEMOTION", "TERMINATION", "POLICY_CHANGE",
    )
    assert isinstance(data.get("severity_points"), int)
    assert isinstance(data.get("justification"), str)
    assert data.get("status") in ("PROPOSED", "ACCEPTED", "SUPERSEDED", "WITHDRAWN")
    assert "version" in data


def assert_closure_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data.get("closure_sequence"), int)
    assert is_valid_uuid(data.get("recipient_employee_id", ""))
    assert data.get("recipient_role") in ("REPORTER", "SUBJECT")
    assert data.get("confidentiality_tier") in (
        "TIER_1_SUMMARY", "TIER_2_LIMITED", "TIER_3_FULL",
    )
    assert isinstance(data.get("body_text"), str)
    assert data.get("delivery_status") in ("QUEUED", "SENT", "FAILED", "SUPPRESSED")
    assert "version" in data


def assert_trend_snapshot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data.get("scope_type") in ("MANAGER", "LOCATION")
    assert isinstance(data.get("scope_key"), str)
    assert data.get("window_kind") in ("ROLLING_90D", "CALENDAR_QUARTER")
    assert is_iso8601_timestamp(data.get("as_of", ""))
    assert isinstance(data.get("closed_case_count"), int)
    assert isinstance(data.get("substantiated_count"), int)
    assert isinstance(data.get("case_rate_per_100"), (int, float))
    assert isinstance(data.get("is_stale"), bool)
    assert "version" in data


def assert_litigation_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data.get("assembled_by"), str)
    assert data.get("status") in ("ASSEMBLING", "READY", "SEALED", "RELEASED")
    assert isinstance(data.get("item_count"), int)
    assert isinstance(data.get("package_version"), int)
    assert "version" in data


def assert_holiday_entry(data: dict):
    """Holiday calendar entries are append-only: id + created_at only (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("holiday_date"), str)
    assert isinstance(data.get("label"), str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "holiday entries must not carry version"
    assert "updated_at" not in data, "holiday entries must not carry updated_at"
