"""Entity assertions and small timestamp utilities.

Each assert_* checks the system-managed properties of PRD §2.4 plus the
presence and type of the entity's own fields. Value-level expectations are
pinned by individual tests, not here.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp ('...Z' or with fractional digits)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def _assert_optional_ts(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_department(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_area_code"], str) and data["service_area_code"]
    assert isinstance(data["annual_budget_cents"], int)
    assert data["signage_status"] in ("CURRENT", "DEFICIENT", "MISSING")
    assert isinstance(data["spent_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["compliance_score"], int)
    assert data["posture"] in ("GOOD_STANDING", "WATCH", "NONCOMPLIANT")


def assert_language_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert isinstance(data["plan_year"], int)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    for field in ("lep_speaker_count", "service_area_population",
                  "encounter_count", "total_encounters"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["lep_share"], (int, float))
    assert isinstance(data["encounter_share"], (int, float))
    assert isinstance(data["threshold_language_safe"], bool)
    assert isinstance(data["priority_language"], bool)
    assert data["status"] in ("DRAFT", "CERTIFIED", "REJECTED")
    assert isinstance(data.get("created_by_user_id"), str)


def assert_vital_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert data["document_type"] in ("FORM", "NOTICE", "GUIDE", "POLICY")
    assert isinstance(data["base_language"], str) and data["base_language"]
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["translated_language_codes"], list)


def assert_translation_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("document_id", ""))
    assert is_valid_uuid(data.get("vendor_contract_id", ""))
    assert isinstance(data["target_language_code"], str) and data["target_language_code"]
    assert isinstance(data["word_count"], int)
    assert isinstance(data["provisional_cost_cents"], int)
    assert isinstance(data["revision_count"], int)
    assert data.get("translator_id") is None or is_valid_uuid(data["translator_id"])
    assert data.get("reviewer_id") is None or is_valid_uuid(data["reviewer_id"])
    assert data.get("submitted_word_count") is None or isinstance(
        data["submitted_word_count"], int)
    assert data.get("final_cost_cents") is None or isinstance(
        data["final_cost_cents"], int)
    assert data.get("superseded_by_job_id") is None or is_valid_uuid(
        data["superseded_by_job_id"])
    assert data["status"] in ("QUEUED", "IN_TRANSLATION", "QUALITY_REVIEW",
                              "APPROVED", "CANCELLED", "SUPERSEDED")


def assert_interpreter(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["language_codes"], list)
    assert isinstance(data["modalities"], list)
    assert data["tier"] in ("PROVISIONAL", "REGISTERED", "CERTIFIED")
    assert is_valid_uuid(data.get("vendor_contract_id", ""))
    _assert_optional_ts(data, "confidentiality_signed_at")
    assert isinstance(data["quality_rating"], int)
    assert isinstance(data["minutes_current_month"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_interpretation_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert data["modality"] in ("PHONE", "VIDEO", "IN_PERSON")
    assert data["encounter_setting"] in ("GENERAL", "MEDICAL", "COURT")
    assert isinstance(data["scheduled_duration_minutes"], int)
    assert data.get("interpreter_id") is None or is_valid_uuid(data["interpreter_id"])
    assert data.get("estimated_cost_cents") is None or isinstance(
        data["estimated_cost_cents"], int)
    assert data.get("actual_minutes") is None or isinstance(data["actual_minutes"], int)
    assert data.get("final_cost_cents") is None or isinstance(
        data["final_cost_cents"], int)
    _assert_optional_ts(data, "completed_at")
    assert isinstance(data["refund_clawed_back"], bool)
    assert data["status"] in ("ASSIGNED", "UNFULFILLED", "COMPLETED", "CANCELLED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("department_id", ""))
    assert data.get("interpretation_request_id") is None or is_valid_uuid(
        data["interpretation_request_id"])
    assert data["category"] in ("NO_INTERPRETER_AVAILABLE", "POOR_QUALITY",
                                "CONFIDENTIALITY_BREACH", "NOTICE_MISSING", "OTHER")
    assert isinstance(data["description"], str)
    assert isinstance(data.get("recorded_by_user_id"), str)
    assert data["status"] in ("RECEIVED", "SUBSTANTIATED", "RESOLVED", "DISMISSED")
    _assert_optional_ts(data, "adjudicated_at")
    _assert_optional_ts(data, "remediation_due_at")
    _assert_optional_ts(data, "closed_at")


def assert_vendor_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["ceiling_cents"], int)
    for field in ("phone_per_minute_cents", "video_per_minute_cents",
                  "in_person_per_minute_cents", "translation_per_word_cents",
                  "in_person_travel_flat_cents", "committed_cents", "spent_cents",
                  "available_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in ("DRAFT", "ACTIVE", "EXHAUSTED")


def assert_language_access_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_year"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    _assert_optional_ts(data, "published_at")
