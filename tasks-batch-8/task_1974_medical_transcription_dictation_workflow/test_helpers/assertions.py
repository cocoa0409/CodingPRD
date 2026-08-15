"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be an integer"


def assert_clinic_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unsigned_report_threshold"], int)
    assert data["unsigned_report_threshold"] >= 1
    assert isinstance(data["aging_tier1_hours"], int)
    assert isinstance(data["aging_tier2_hours"], int)
    assert data["aging_tier1_hours"] >= 1
    assert data["aging_tier1_hours"] < data["aging_tier2_hours"]
    assert isinstance(data["payment_grace_days"], int)
    assert isinstance(data["billing_hold"], bool)
    assert isinstance(data["suspended_provider_count"], int)


def assert_sla_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_account_id", ""))
    assert data["priority"] in ("STAT", "URGENT", "ROUTINE")
    assert isinstance(data["tat_minutes"], int) and data["tat_minutes"] > 0
    assert isinstance(data["rate_per_line_cents"], int) and data["rate_per_line_cents"] > 0
    assert isinstance(data["breach_credit_pct"], int)
    assert 0 <= data["breach_credit_pct"] <= 100
    assert data["measurement_basis"] in ("END_TO_END", "PRODUCTION_WINDOW")


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_account_id", ""))
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["specialty"] in ("RADIOLOGY", "CARDIOLOGY", "ORTHOPEDICS", "GENERAL")
    assert data["status"] in ("ACTIVE", "WARNING", "SUSPENDED")
    assert isinstance(data["unsigned_tier1_count"], int)
    assert isinstance(data["unsigned_aged_count"], int)
    assert data["suspension_reason"] in (None, "UNSIGNED_REPORT_AGING")


def assert_editor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["status"] in ("ACTIVE", "PROBATION", "SUSPENDED")
    assert isinstance(data["rolling_quality_score"], (int, float))
    assert isinstance(data["qa_review_count"], int)
    assert data["skill_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["max_concurrent_claims"], int)
    assert isinstance(data["active_claim_count"], int)


def assert_shift_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("editor_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))


def assert_dictation_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("clinic_account_id", ""))
    assert data["work_type"] in (
        "CONSULT", "OP_NOTE", "DISCHARGE_SUMMARY", "CLINIC_NOTE", "RADIOLOGY_REPORT",
    )
    assert data["priority"] in ("STAT", "URGENT", "ROUTINE")
    assert isinstance(data["audio_duration_seconds"], int) and data["audio_duration_seconds"] > 0
    assert data["workflow_status"] in ("QUEUED", "EDITING", "SUBMITTED", "DELIVERED", "CANCELLED")
    assert data["escalation_level"] in ("NONE", "ESCALATED", "CRITICAL")
    assert isinstance(data["rework_count"], int)
    assert isinstance(data["preempted_count"], int)
    assert isinstance(data["asr_char_estimate"], int)
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_transcript(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dictation_job_id", ""))
    assert is_valid_uuid(data.get("editor_id", ""))
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["final_text"], str)
    assert isinstance(data["visible_char_count"], int)
    assert isinstance(data["line_count"], int)
    assert data["status"] in ("SUBMITTED", "DELIVERED", "REJECTED", "RETURNED", "SIGNED", "AMENDED")
    assert data["aging_tier"] in ("NONE", "TIER_1", "TIER_2")


def assert_qa_review(data: dict):
    """PRD §2.5: the QA review is append-only — id + created_at only, no
    updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only QAReview must not carry updated_at"
    assert "version" not in data, "append-only QAReview must not carry version"
    assert is_valid_uuid(data.get("dictation_job_id", ""))
    assert isinstance(data["critical_error_count"], int) and data["critical_error_count"] >= 0
    assert isinstance(data["major_error_count"], int) and data["major_error_count"] >= 0
    assert isinstance(data["minor_error_count"], int) and data["minor_error_count"] >= 0
    assert isinstance(data["accuracy_score"], (int, float))
    assert data["outcome"] in ("PASS", "FAIL")


def assert_provider_template(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["work_type"] in (
        "CONSULT", "OP_NOTE", "DISCHARGE_SUMMARY", "CLINIC_NOTE", "RADIOLOGY_REPORT",
    )
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["body_text"], str)
    assert isinstance(data["is_active"], bool)


def assert_macro(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["shortcut"], str) and len(data["shortcut"]) > 0
    assert isinstance(data["expansion_text"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_billing_period(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_account_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["status"] in ("OPEN", "CLOSED", "FINALIZED", "DISPUTED", "SETTLED")
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["credit_amount_cents"], int)
    assert isinstance(data["net_amount_cents"], int)


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("billing_period_id", ""))
    assert is_valid_uuid(data.get("transcript_id", ""))
    assert data["priority"] in ("STAT", "URGENT", "ROUTINE")
    assert isinstance(data["rate_per_line_cents"], int)
    assert isinstance(data["provisional_line_count"], int)
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["status"] in ("PROVISIONAL", "FINAL", "CREDIT_REVERSED")


def assert_billing_rollup_identity(period: dict):
    """PRD §3.9: the invariant gross == net + credit holds at every step."""
    gross = period["gross_amount_cents"]
    net = period["net_amount_cents"]
    credit = period["credit_amount_cents"]
    assert net + credit == gross, (
        f"Rollup identity violated: net {net} + credit {credit} != gross {gross}"
    )
