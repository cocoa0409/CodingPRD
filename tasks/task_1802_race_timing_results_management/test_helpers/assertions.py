"""Entity assertions and domain invariant checkers.

Field names follow the PRD narratives exactly. Timestamp comparisons in tests
should use parse_iso() so assertions compare instants, not serializations.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(ts, str), f"expected ISO timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_common_fields(data: dict):
    """PRD §2.5: id + created_at + updated_at + version on primary resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_race(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["race_date"]), "race_date must be ISO 8601"
    assert isinstance(data["distance_km"], (int, float)) and data["distance_km"] > 0
    assert data["course_type"] in ("CERTIFIED_COURSE", "UNCERTIFIED_COURSE")
    assert isinstance(data["course_time_limit_minutes"], int) \
        and data["course_time_limit_minutes"] > 0
    assert data.get("qualifying_standard_ms") is None or \
        isinstance(data["qualifying_standard_ms"], int)
    assert data["status"] in (
        "DRAFT", "REGISTRATION_OPEN", "TIMING_LOCKED", "IN_PROGRESS",
        "PROVISIONAL_PUBLISHED", "FINALIZED", "AMENDMENT_OPEN",
    )
    assert isinstance(data.get("amendment_count"), int)
    for stamp in ("timing_locked_at", "provisional_published_at",
                  "protest_window_closes_at", "finalized_at"):
        assert data.get(stamp) is None or is_iso8601_timestamp(data[stamp])


def assert_wave(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert isinstance(data["wave_index"], int) and data["wave_index"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start_time"])
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] > 0
    assert data.get("actual_start_time") is None or is_iso8601_timestamp(data["actual_start_time"])
    assert data["status"] in ("SCHEDULED", "STARTED")


def assert_timing_point(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert isinstance(data["point_index"], int) and data["point_index"] >= 1
    assert data["kind"] in ("START", "SPLIT", "FINISH")
    assert isinstance(data["distance_km"], (int, float)) and data["distance_km"] >= 0
    assert isinstance(data["device_id"], str) and data["device_id"]
    assert is_iso8601_timestamp(data["deploy_at"])
    assert is_iso8601_timestamp(data["expected_teardown_at"])
    assert data["status"] in ("PLANNED", "DEPLOYED")


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["wave_id"])
    assert data.get("chip_id") is None or is_valid_uuid(data["chip_id"])
    assert isinstance(data["bib_number"], str) and data["bib_number"]
    assert isinstance(data["participant_name"], str) and data["participant_name"]
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert data["gender"] in ("M", "F")
    assert data["lifecycle_status"] in ("REGISTERED", "CONFIRMED", "CHECKED_IN", "WITHDRAWN")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["age_on_race_day"], int) and data["age_on_race_day"] >= 0
    assert isinstance(data["age_group"], str) and data["age_group"]


def assert_chip(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["chip_code"], str) and data["chip_code"]
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "LOST")
    assert data.get("current_registration_id") is None or \
        is_valid_uuid(data["current_registration_id"])


def assert_timing_read(data: dict):
    """Append-only log row (PRD §2.5): id + created_at only; NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TimingRead must not carry updated_at"
    assert "version" not in data, "TimingRead must not carry version"
    assert is_valid_uuid(data["timing_point_id"])
    assert is_valid_uuid(data["chip_id"])
    assert is_iso8601_timestamp(data["read_timestamp"])
    assert data["status"] in ("SCORED", "REJECTED", "EXCLUDED")
    assert data.get("reject_reason") is None or isinstance(data["reject_reason"], str)
    assert data.get("adjusted_by_correction_id") is None or \
        is_valid_uuid(data["adjusted_by_correction_id"])


def assert_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["registration_id"])
    assert data["status"] in ("PROVISIONAL", "OFFICIAL", "AMENDED", "EXCLUDED")
    assert data.get("exclusion_reason") is None or \
        data["exclusion_reason"] in ("DNF", "DQ", "COURSE_CUT_SUSPECT")
    assert data.get("chip_time_ms") is None or isinstance(data["chip_time_ms"], int)
    assert data.get("gun_time_ms") is None or isinstance(data["gun_time_ms"], int)
    assert data.get("finish_timestamp") is None or is_iso8601_timestamp(data["finish_timestamp"])
    assert isinstance(data["completed_splits"], int) and data["completed_splits"] >= 0
    assert data.get("overall_rank_gun") is None or \
        (isinstance(data["overall_rank_gun"], int) and data["overall_rank_gun"] >= 1)
    assert data.get("age_group_rank_chip") is None or \
        (isinstance(data["age_group_rank_chip"], int) and data["age_group_rank_chip"] >= 1)
    assert isinstance(data["qualified"], bool)
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_result_flag(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["flag_type"] in ("DNF", "DQ", "COURSE_CUT_SUSPECT")
    assert data["origin"] in ("AUTO", "MANUAL")
    assert data["status"] in ("RAISED", "CONFIRMED", "DISMISSED")


def assert_protest(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["registration_id"])
    assert is_valid_uuid(data["timing_read_id"])
    assert data["requested_action"] in ("EXCLUDE_READ", "REINSTATE_READ", "ADJUST_READ_TIME")
    assert isinstance(data["reason"], str)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in ("FILED", "UPHELD", "DISMISSED")
    assert data.get("resolved_by_user_id") is None or isinstance(data["resolved_by_user_id"], str)


def assert_correction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["timing_read_id"])
    assert data["kind"] in ("EXCLUDE_READ", "REINSTATE_READ", "ADJUST_READ_TIME")
    assert isinstance(data["reason"], str)
    assert data.get("protest_id") is None or is_valid_uuid(data["protest_id"])
    assert data["status"] in ("FILED", "APPROVED", "REJECTED")
    assert data.get("adjudicated_by_user_id") is None or \
        isinstance(data["adjudicated_by_user_id"], str)


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert data["status"] in ("ISSUED", "REVOKED")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["qualified_count"], int) and data["qualified_count"] >= 0
    assert data.get("revocation_reason") is None or isinstance(data["revocation_reason"], str)


def assert_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["registration_id"])
    assert isinstance(data["category"], str) and data["category"]
    assert isinstance(data["place"], int) and 1 <= data["place"] <= 3
    assert data["basis"] in ("GUN", "CHIP")
    assert isinstance(data["basis_time_ms"], int) and data["basis_time_ms"] >= 0
    assert data["status"] in ("PROJECTED", "CONFIRMED", "REVOKED")


def assert_award_singleton_per_category_place(awards: list):
    """PRD §3.6: at most one non-REVOKED award per race, category, and place."""
    active = {}
    for award in awards:
        if award["status"] == "REVOKED":
            continue
        key = (award["category"], award["place"])
        assert key not in active, (
            f"two non-REVOKED awards for {key}: {active[key]['id']} and {award['id']}"
        )
        active[key] = award
