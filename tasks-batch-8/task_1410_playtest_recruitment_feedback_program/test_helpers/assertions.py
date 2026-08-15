"""Entity assertions and small domain helpers.

Timestamps are compared as parsed instants (never as strings) so that any
ISO 8601 UTC serialization with three fractional digits satisfies them.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(value: str, expected_iso: str, label: str = "timestamp"):
    actual = parse_instant(value)
    expected = parse_instant(expected_iso)
    assert actual == expected, f"{label}: expected instant {expected_iso}, got {value}"


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("age_years"), int)
    assert isinstance(data.get("region_code"), str)
    assert isinstance(data.get("platform_tags"), list)
    assert isinstance(data.get("verified_platform_tags"), list)
    assert data.get("status") in ("REGISTERED", "ACTIVE", "SUSPENDED", "BANNED")
    assert isinstance(data.get("no_show_strikes"), int)
    assert isinstance(data.get("risk_score"), int)
    assert 0 <= data["risk_score"] <= 100, "risk_score is capped at 100 (PRD §3.9)"


def assert_moderator(data: dict):
    _assert_common(data)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("email"), str)
    assert data.get("status") in ("ACTIVE", "INACTIVE")


def assert_study(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("code"), str)
    assert isinstance(data.get("min_age"), int)
    assert isinstance(data.get("max_age"), int)
    assert isinstance(data.get("allowed_regions"), list)
    assert isinstance(data.get("required_platforms"), list)
    assert isinstance(data.get("cohort_capacity"), int)
    assert isinstance(data.get("incentive_budget_cents"), int)
    assert data.get("status") in ("DRAFT", "RECRUITING", "CLOSED", "ANALYSIS", "COMPLETED")
    assert isinstance(data.get("enrolled_count"), int)
    assert isinstance(data.get("budget_committed_cents"), int)
    assert isinstance(data.get("budget_spent_cents"), int)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data.get("status") in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                                  "APPROVED", "ENROLLED", "REJECTED", "WITHDRAWN")


def assert_nda_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data.get("version_label"), str)
    assert isinstance(data.get("body_text"), str)
    assert data.get("status") in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_nda_signature(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert data.get("status") in ("PENDING", "SIGNED", "VOIDED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_build(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data.get("build_label"), str)
    assert isinstance(data.get("max_keys"), int)
    assert isinstance(data.get("key_ttl_hours"), int)
    assert data.get("status") in ("STAGED", "RELEASED", "RETIRED")
    assert isinstance(data.get("keys_active_count"), int)


def assert_access_key(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("build_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    key_code = data.get("key_code", "")
    assert isinstance(key_code, str)
    if key_code:
        # PRD §3.4: the literal KEY- followed by twelve uppercase alphanumerics.
        assert key_code.startswith("KEY-"), "key_code carries the KEY- prefix"
        suffix = key_code[4:]
        assert len(suffix) == 12 and suffix.isalnum() and suffix.upper() == suffix
    assert data.get("status") in ("ISSUED", "REDEEMED", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data.get("station_code"), str)
    assert isinstance(data.get("location"), str)
    assert isinstance(data.get("equipment_tags"), list)
    assert data.get("status") in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert data.get("mode") in ("REMOTE", "IN_LAB")
    assert data.get("status") in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data.get("seat_capacity"), int)
    assert isinstance(data.get("seats_taken"), int)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data.get("status") in ("BOOKED", "WAITLISTED", "PROMOTED",
                                  "ATTENDED", "NO_SHOW", "CANCELLED")


def assert_instrument(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("questions"), list) and data["questions"]
    assert data.get("status") in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_survey_response(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instrument_id", ""))
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data.get("answers"), list)
    assert data.get("status") in ("DRAFT", "SUBMITTED")


def assert_feedback_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data.get("title"), str)
    assert data.get("severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data.get("reach_count"), int)
    assert 0 <= data.get("reproducibility_pct", -1) <= 1
    assert data.get("status") in ("NEW", "TRIAGED", "NEEDS_INFO",
                                  "ROUTED", "RESOLVED", "WONT_FIX")


def assert_payout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data.get("amount_provisional_cents"), int)
    assert data.get("status") in ("DRAFT", "PENDING_APPROVAL", "APPROVED",
                                  "REJECTED", "ISSUED", "VOID")


def assert_breach_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data.get("evidence_summary"), str)
    assert data.get("severity") in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data.get("reported_by_user_id"), str)
    assert isinstance(data.get("reported_by_role"), str)
    assert data.get("status") in ("REPORTED", "UNDER_INVESTIGATION",
                                  "DISMISSED", "SUBSTANTIATED", "SANCTIONED")


def assert_exposure_record(data: dict):
    """Append-only journal row (PRD §2.5): id + created_at only; the record
    carries NO updated_at and NO version keys."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records carry no updated_at"
    assert "version" not in data, "append-only records carry no version"
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("build_id", ""))
    assert is_valid_uuid(data.get("study_id", ""))
    assert data.get("event_type") in ("KEY_ISSUED", "KEY_REDEEMED",
                                      "KEY_REVOKED", "KEY_EXPIRED")
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
