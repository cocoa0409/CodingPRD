"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. The ItemResponse record is append-only
and must NOT expose updated_at/version (PRD common-resource-properties
section). Nullable system-stamped fields (retired_at, finalized_at,
published_at, ...) are checked for type only when present.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 0, (
        f"version must be an integer >= 0, got {data.get('version')!r}"
    )


def _assert_optional_timestamp(data: dict, field: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 when set"


def assert_assessment_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["subject"] in ("MATH", "ELA", "SCIENCE", "SOCIAL_STUDIES")
    assert isinstance(data["grade_level"], int) and 3 <= data["grade_level"] <= 12
    assert isinstance(data["admin_year"], int)
    assert isinstance(data["current_period_utc"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ARCHIVED")


def assert_content_standard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["standard_code"], str) and data["standard_code"]
    assert isinstance(data["strand"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["depth_of_knowledge"], int) and 1 <= data["depth_of_knowledge"] <= 4
    assert data["status"] in ("ACTIVE", "DEPRECATED")


def assert_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert isinstance(data["primary_standard_id"], str)
    assert data["item_type"] in ("MC", "MS", "EBSR", "TE", "CR")
    assert isinstance(data["stimulus_html"], str)
    assert isinstance(data["options_json"], dict)
    assert isinstance(data["max_score_points"], int) and 1 <= data["max_score_points"] <= 6
    assert isinstance(data["author_user_id"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CONTENT_REVIEW", "BIAS_REVIEW",
        "FIELD_TEST_ELIGIBLE", "FIELD_TESTING", "STATS_REVIEW",
        "OPERATIONAL", "RETIRED", "REJECTED",
    )
    assert data["security_posture"] in ("UNSECURED", "SECURED", "EXPOSED", "COMPROMISED")
    assert data["content_review_outcome"] in ("PENDING", "PASSED", "FAILED", "REVISE")
    assert data["bias_review_outcome"] in ("PENDING", "PASSED", "FAILED", "REVISE")
    assert isinstance(data["revision_cycle_count"], int) and data["revision_cycle_count"] >= 0
    assert isinstance(data["field_test_attempt_count"], int) and data["field_test_attempt_count"] >= 0
    assert isinstance(data["operational_exposure_count"], int) and data["operational_exposure_count"] >= 0
    assert isinstance(data["exposure_cap"], int) and data["exposure_cap"] >= 1
    _assert_optional_timestamp(data, "retired_at")
    if data.get("retirement_reason") is not None:
        assert data["retirement_reason"] in (
            "STATISTICAL_FAIL", "BIAS_CONFIRMED", "OVER_EXPOSED",
            "CONTENT_DEPRECATED", "MANUAL",
        )


def assert_review_committee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert data["committee_kind"] in ("CONTENT", "BIAS_SENSITIVITY")
    assert isinstance(data["name"], str)
    assert isinstance(data["quorum_size"], int) and 2 <= data["quorum_size"] <= 7
    assert data["status"] in ("ACTIVE", "DISSOLVED")


def assert_review_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["committee_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["scheduled_at"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["agenda_item_ids"], list)
    _assert_optional_timestamp(data, "started_at")
    _assert_optional_timestamp(data, "closed_at")


def assert_review_verdict(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["reviewer_user_id"], str)
    assert data["verdict"] in ("ACCEPT", "REJECT", "REVISE")
    assert isinstance(data["soft_deleted"], bool)


def assert_field_test_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["window_label"], str)
    assert isinstance(data["start_utc"], str)
    assert isinstance(data["end_utc"], str)
    assert isinstance(data["target_sample_size"], int)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_item_response(data: dict):
    """Append-only record: id + created_at only; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "item responses must not expose updated_at"
    assert "version" not in data, "item responses must not expose version"
    assert isinstance(data["window_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["student_anon_id"], str)
    assert isinstance(data["response_timestamp"], str)
    assert isinstance(data["attempt_duration_seconds"], int) and data["attempt_duration_seconds"] >= 0
    assert isinstance(data["raw_score"], int)
    assert isinstance(data["excluded"], bool)


def assert_item_statistic(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["window_id"], str)
    assert isinstance(data["n_responses"], int) and data["n_responses"] >= 0
    assert isinstance(data["p_value"], (int, float))
    assert isinstance(data["point_biserial"], (int, float))
    assert data["stats_kind"] in ("PROVISIONAL", "FINAL")
    _assert_optional_timestamp(data, "finalized_at")
    if data.get("pass_flag") is not None:
        assert data["pass_flag"] in ("PASS", "FAIL_BORDERLINE", "FAIL_SEVERE")


def assert_test_blueprint(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["blueprint_code"], str)
    assert isinstance(data["sections"], list) and len(data["sections"]) >= 1
    assert data["status"] in ("DRAFT", "LOCKED", "SUPERSEDED")


def assert_test_form(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["blueprint_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["form_code"], str)
    assert isinstance(data["intended_admin_date"], str)
    assert data["status"] in ("ASSEMBLING", "ASSEMBLED", "EQUATED", "PUBLISHED", "ARCHIVED")
    _assert_optional_timestamp(data, "assembled_at")
    _assert_optional_timestamp(data, "published_at")


def assert_form_item_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["form_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["section_index"], int) and data["section_index"] >= 0
    assert isinstance(data["position_in_section"], int) and data["position_in_section"] >= 1
    assert isinstance(data["is_anchor"], bool)
    assert isinstance(data["points_possible"], int) and data["points_possible"] >= 1


def assert_equating_link(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["source_form_id"], str)
    assert isinstance(data["target_form_id"], str)
    assert isinstance(data["anchor_item_ids"], list)
    assert isinstance(data["scaling_slope"], (int, float))
    assert isinstance(data["scaling_intercept"], (int, float))


def assert_item_variant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_id"], str)
    assert data["variant_kind"] in ("TRANSLATION", "ACCOMMODATION")
    assert isinstance(data["stimulus_html"], str)
    assert isinstance(data["options_json"], dict)
    assert data["status"] in ("DRAFT", "APPROVED", "REJECTED")


def assert_access_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["grantee_user_id"], str)
    assert data["grant_scope"] in (
        "ITEM_READ", "ITEM_WRITE", "STATS_READ", "FORM_ASSEMBLE", "GRANT_ADMIN",
    )
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    _assert_optional_timestamp(data, "revoked_at")


def assert_validity_dossier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["form_id"], str)
    assert data["dossier_kind"] in ("TECHNICAL_MANUAL", "VALIDITY_EVIDENCE", "RELIABILITY_REPORT")
    assert isinstance(data["content_md"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    _assert_optional_timestamp(data, "published_at")


def assert_exposure_invariant(item: dict):
    """Exposure accounting invariant: the count is a whole number, never
    negative, and never above the item's exposure cap."""
    count = item["operational_exposure_count"]
    assert isinstance(count, int) and count >= 0, "exposure count never negative"
    assert count <= item["exposure_cap"] or item["status"] == "RETIRED", (
        "an item at/over its exposure cap must already be retired"
    )
