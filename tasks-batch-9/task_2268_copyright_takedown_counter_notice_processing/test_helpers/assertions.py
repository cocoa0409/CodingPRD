"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4 mutable-resource system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, what: str = "resource"):
    """PRD §2.4 append-only exception: only id + created_at are carried."""
    assert is_valid_uuid(data.get("id", "")), f"{what} id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what} created_at must be ISO 8601 UTC"
    )
    assert "version" not in data, f"{what} must not carry version (append-only)"
    assert "updated_at" not in data, f"{what} must not carry updated_at (append-only)"


def assert_money_int(value, label: str = "amount"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_two_decimal_places(value, label: str = "value"):
    """PRD §2.8: two-decimal quantities never carry a third significant digit."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value!r}"
    )


def assert_four_decimal_places(value, label: str = "value"):
    """PRD §2.8: match confidence is carried to four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == float(value), (
        f"{label} must carry at most 4 decimal places, got {value!r}"
    )


def assert_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["service_domain"], str) and data["service_domain"]
    assert isinstance(data["designated_agent_registered"], bool)
    assert isinstance(data["repeat_infringer_policy_published"], bool)
    assert isinstance(data["safe_harbor_score"], int)
    assert data["safe_harbor_status"] in ("ELIGIBLE", "AT_RISK", "FORFEITED")


def assert_designated_agent(data: dict):
    assert_common_fields(data)
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert isinstance(data["agent_name"], str) and data["agent_name"]
    assert isinstance(data["agent_email"], str) and data["agent_email"]
    assert isinstance(data["agent_phone"], str) and data["agent_phone"]
    assert isinstance(data["mailing_address"], str) and data["mailing_address"]
    assert data["registration_status"] in ("DRAFT", "SUBMITTED", "REGISTERED", "LAPSED")


def assert_policy(data: dict):
    assert_common_fields(data)
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert isinstance(data["policy_text"], str) and data["policy_text"]
    assert isinstance(data["strike_expiry_days"], int)
    assert isinstance(data["decay_step_days"], int)
    assert isinstance(data["limitation_threshold_points"], (int, float))
    assert isinstance(data["termination_threshold_points"], (int, float))
    assert data["limitation_threshold_points"] < data["termination_threshold_points"]
    assert isinstance(data["appeal_window_days"], int)
    assert isinstance(data["counter_notice_window_days"], int)
    assert isinstance(data["dispute_window_days"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert isinstance(data["handle"], str) and data["handle"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["standing"] in ("ACTIVE", "LIMITED", "TERMINATED")
    assert_two_decimal_places(data["strike_points"], "strike_points")
    assert isinstance(data["upload_restricted"], bool)
    assert isinstance(data["notified_count"], int)
    assert isinstance(data["available_content_count"], int)


def assert_content_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["content_url"], str) and data["content_url"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["fingerprint_hash"], str) and data["fingerprint_hash"]
    assert data["availability_status"] in ("AVAILABLE", "DISABLED", "RESTORED", "PURGED")
    assert data["dispute_status"] in (
        "NONE", "UNDER_NOTICE", "COUNTER_NOTICED", "RESTORATION_PENDING", "RESOLVED",
    )


def assert_rights_holder(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["reference_file_quota"], int)
    assert isinstance(data["daily_item_quota"], int)
    assert data["enrollment_status"] in ("PROSPECT", "ENROLLED", "SUSPENDED")
    assert data["program_tier"] in ("STANDARD", "VERIFIED", "TRUSTED")
    assert isinstance(data["notices_processed"], int)
    assert isinstance(data["withdrawn_count"], int)
    assert isinstance(data["rejected_count"], int)
    assert isinstance(data["misrepresentation_count"], int)
    assert_two_decimal_places(data["abuse_score"], "abuse_score")


def assert_notice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["rights_holder_id"], str) and data["rights_holder_id"]
    assert data["submission_channel"] in ("WEB_FORM", "EMAIL", "API_BULK")
    assert isinstance(data["claimed_urls"], list) and data["claimed_urls"]
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100
    assert data["status"] in (
        "RECEIVED", "VALIDATED", "REJECTED", "PROCESSED", "WITHDRAWN", "CLOSED",
    )
    assert isinstance(data["matched_claim_count"], int)
    assert isinstance(data["unmatched_url_count"], int)


def assert_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["notice_id"], str) and data["notice_id"]
    assert isinstance(data["content_item_id"], str) and data["content_item_id"]
    assert isinstance(data["rights_holder_id"], str) and data["rights_holder_id"]
    assert isinstance(data["matched_url"], str) and data["matched_url"]
    # PRD §3.6: a claim carried on the URL match alone leaves both
    # reference_file_id and match_confidence null.
    if data["match_confidence"] is not None:
        assert_four_decimal_places(data["match_confidence"], "match_confidence")
    else:
        assert data["reference_file_id"] is None, (
            "match_confidence may only be null when no reference file was selected"
        )
    assert data["status"] in (
        "MATCHED", "DISABLED", "COUNTER_NOTICED", "RESTORATION_SCHEDULED",
        "RESTORED", "UPHELD", "WITHDRAWN",
    )
    assert isinstance(data["dispute_window_days"], int)
    assert isinstance(data["counter_notice_window_days"], int)


def assert_counter_notice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["claim_id"], str) and data["claim_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["subscriber_name"], str) and data["subscriber_name"]
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100
    assert data["status"] in (
        "RECEIVED", "VALIDATED", "FORWARDED", "RESTORATION_SCHEDULED",
        "RESTORED", "BLOCKED_BY_SUIT", "SUPERSEDED", "REJECTED",
    )


def assert_strike(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["claim_id"], str) and data["claim_id"]
    assert_two_decimal_places(data["weight"], "weight")
    assert_two_decimal_places(data["base_points"], "base_points")
    assert_two_decimal_places(data["effective_points"], "effective_points")
    assert data["reason"] in ("NOTICE_PROCESSED", "CLAIM_UPHELD")
    assert data["status"] in ("ACTIVE", "DECAYED", "EXPIRED", "VOIDED")
    assert is_iso8601_timestamp(data["accrued_at"])


def assert_termination_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert_two_decimal_places(data["trigger_points"], "trigger_points")
    assert data["status"] in ("OPEN", "EXECUTED", "APPEAL_FILED", "VACATED", "CLOSED")
    assert data["decision"] in (None, "UPHELD", "VACATED")


def assert_misrepresentation_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["rights_holder_id"], str) and data["rights_holder_id"]
    assert isinstance(data["claim_id"], str) and data["claim_id"]
    assert isinstance(data["allegation"], str) and data["allegation"]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["status"] in ("OPEN", "SUBSTANTIATED", "DISMISSED")
    assert isinstance(data["affected_claim_count"], int)
    assert isinstance(data["disabled_day_count"], int)
    assert_money_int(data["base_penalty_cents"], "base_penalty_cents")
    assert_money_int(data["surcharge_cents"], "surcharge_cents")
    assert_money_int(data["total_penalty_cents"], "total_penalty_cents")


def assert_reference_file(data: dict):
    assert_common_fields(data)
    assert isinstance(data["rights_holder_id"], str) and data["rights_holder_id"]
    assert isinstance(data["work_title"], str) and data["work_title"]
    assert isinstance(data["fingerprint_hash"], str) and data["fingerprint_hash"]
    assert data["status"] in ("PENDING", "ACTIVE", "QUARANTINED")
    assert isinstance(data["match_count"], int)


def assert_ingestion_batch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["rights_holder_id"], str) and data["rights_holder_id"]
    assert isinstance(data["item_count"], int)
    assert isinstance(data["rolling_item_total"], int)
    assert data["status"] in ("ACCEPTED", "PROCESSING", "COMPLETED", "REJECTED")
    assert isinstance(data["notices_created"], int)
    assert isinstance(data["matched_count"], int)
    assert isinstance(data["unmatched_count"], int)


def assert_safe_harbor_audit(data: dict):
    """SafeHarborAudit is append-only: no updated_at, no version."""
    assert_append_only_fields(data, "SafeHarborAudit")
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert_two_decimal_places(data["median_response_hours"], "median_response_hours")
    assert isinstance(data["overdue_restoration_count"], int)
    assert isinstance(data["termination_compliance"], bool)
    assert isinstance(data["contact_published"], bool)
    assert_two_decimal_places(data["response_component"], "response_component")
    assert_two_decimal_places(data["restoration_component"], "restoration_component")
    assert_two_decimal_places(data["termination_component"], "termination_component")
    assert_two_decimal_places(data["contact_component"], "contact_component")
    assert isinstance(data["compliance_score"], int)
    assert data["resulting_status"] in ("ELIGIBLE", "AT_RISK", "FORFEITED")


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Compare two UTC instants ignoring fractional-second formatting."""
    from datetime import datetime, timezone

    def parse(value: str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC, got {actual!r}"
    assert parse(actual) == parse(expected_iso), (
        f"{label} must be {expected_iso}, got {actual}"
    )
