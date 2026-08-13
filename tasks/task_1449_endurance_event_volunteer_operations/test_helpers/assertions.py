"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape of one entity against the PRD
contract (PRD §2.6 common fields plus the entity's own fields from §3).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    EventStatus, TerrainType, RequiredSkill, TrainingModule, RoleEntryStatus,
    ShiftStatus, GroupStatus, VolunteerStatus, TrainingRecordStatus,
    SignupStatus, SignupOrigin, DistributionKind, DistributionStatus,
    HourLogStatus, DebriefStatus, AdjustmentStatus, RecognitionTier,
)


def _assert_common(data: dict):
    """PRD §2.6: id (UUID), created_at/updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    for f in ("event_start_at", "event_end_at", "early_access_opens_at",
              "signup_opens_at", "signup_closes_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"{f} must be ISO 8601"
    assert data["status"] in [s.value for s in EventStatus]


def assert_course_segment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert isinstance(data["mile_start"], (int, float))
    assert isinstance(data["mile_end"], (int, float))
    assert data["mile_end"] > data["mile_start"], "mile_end must exceed mile_start"
    assert data["terrain_type"] in [t.value for t in TerrainType]


def assert_role_catalog_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["role_code"], str) and data["role_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["min_age_years"], int)
    assert data["required_skill"] in [s.value for s in RequiredSkill]
    assert data["required_training_module"] in [m.value for m in TrainingModule]
    assert 0 < data["credit_weight"] <= 3, "credit_weight must be > 0 and <= 3"
    assert data["status"] in [s.value for s in RoleEntryStatus]


def assert_shift(data: dict):
    _assert_common(data)
    for f in ("event_id", "role_entry_id", "segment_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["required_headcount"], int) and data["required_headcount"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert isinstance(data["checked_in_count"], int) and data["checked_in_count"] >= 0
    assert isinstance(data["understaffed_alert"], bool)
    assert data["status"] in [s.value for s in ShiftStatus]


def assert_shift_invariants(data: dict):
    """PRD §3.2: counters stay within sane bounds relative to headcount."""
    assert 0 <= data["checked_in_count"] <= data["confirmed_count"]
    assert data["confirmed_count"] >= 0


def assert_fundraising_group(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["charity_code"], str) and data["charity_code"]
    assert data["status"] in [s.value for s in GroupStatus]


def assert_volunteer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert isinstance(data["skill_tags"], list)
    assert isinstance(data["float_opt_in"], bool)
    assert isinstance(data["is_returning"], bool)
    assert data["status"] in [s.value for s in VolunteerStatus]
    assert isinstance(data["age_years_on_event"], int)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_training_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["module_code"] in [m.value for m in TrainingModule if m.value != "NONE"]
    assert data["status"] in [s.value for s in TrainingRecordStatus]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 1
    if data["status"] == "PASSED":
        assert is_iso8601_timestamp(data.get("passed_at", "")), "passed_at set when PASSED"
        assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until set when PASSED"


def assert_signup(data: dict):
    _assert_common(data)
    for f in ("event_id", "volunteer_id", "shift_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a UUID"
    assert data["status"] in [s.value for s in SignupStatus]
    assert data["origin"] in [o.value for o in SignupOrigin]
    assert isinstance(data["is_captain"], bool)
    assert is_iso8601_timestamp(data.get("requested_at", "")), "requested_at must be ISO 8601"


def assert_supply_inventory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert isinstance(data["quantity_total"], int) and data["quantity_total"] >= 0
    assert isinstance(data["quantity_issued"], int) and data["quantity_issued"] >= 0
    assert data["quantity_issued"] <= data["quantity_total"], "issued must not exceed total"


def assert_distribution_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("signup_id", ""))
    assert data["kind"] in [k.value for k in DistributionKind]
    assert data["status"] in [s.value for s in DistributionStatus]
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    if data["kind"] == "CREDENTIAL":
        assert data.get("inventory_id") is None, "credentials carry a null inventory_id"
    else:
        assert is_valid_uuid(data.get("inventory_id", "")), "supply items carry a live inventory_id"


def assert_hour_log(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("signup_id", ""))
    assert data["status"] in [s.value for s in HourLogStatus]
    assert isinstance(data["break_minutes"], int) and data["break_minutes"] >= 0
    assert isinstance(data["raw_minutes"], int) and data["raw_minutes"] >= 0
    assert isinstance(data["claimed_hours"], (int, float)) and data["claimed_hours"] >= 0
    assert isinstance(data["credited_hours"], (int, float)) and data["credited_hours"] >= 0


def assert_debrief_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("author_volunteer_id", ""))
    assert isinstance(data["headcount_actual"], int) and data["headcount_actual"] >= 0
    assert isinstance(data["role_effectiveness_rating"], int)
    assert 1 <= data["role_effectiveness_rating"] <= 5
    assert isinstance(data["supply_shortage_flag"], bool)
    assert data["status"] in [s.value for s in DebriefStatus]


def assert_role_adjustment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("role_entry_id", ""))
    assert is_valid_uuid(data.get("debrief_report_id", ""))
    assert isinstance(data["proposed_retire"], bool)
    assert data["status"] in [s.value for s in AdjustmentStatus]


def assert_credit_summary(data: dict):
    assert isinstance(data["provisional_effective_hours"], (int, float))
    assert isinstance(data["settled_effective_hours"], (int, float))
    for f in ("provisional_credit_cents", "settled_credit_cents",
              "sponsor_match_cents", "total_settled_credit_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"


def assert_recognition_summary(data: dict):
    assert isinstance(data["projected_points"], int)
    assert isinstance(data["official_points"], int)
    assert data["recognition_tier"] in [t.value for t in RecognitionTier]
    assert isinstance(data["captain_shift_count"], int) and data["captain_shift_count"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
