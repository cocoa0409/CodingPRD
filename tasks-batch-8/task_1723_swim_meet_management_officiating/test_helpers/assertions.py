"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgeGroup,
    DisqualificationStatus,
    EventEntryStatus,
    LaneStatus,
    MeetRecordStatus,
    MeetStatus,
    OfficialAssignmentStatus,
    QualificationStatus,
    ReconciledVariant,
    ReconciliationStatus,
    RelayTeamStatus,
    ResultStatus,
    SwimEventStatus,
    SwimmerStatus,
    TeamStatus,
)


def _assert_common_fields(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_meet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["meet_name"], str) and data["meet_name"]
    assert data["course"] in ["SCY", "SCM", "LCM"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["entry_deadline_utc"], str)
    assert isinstance(data["lane_count"], int)
    assert isinstance(data["points_table"], list)
    assert isinstance(data["relay_points_multiplier"], int)
    assert isinstance(data["max_individual_entries_per_swimmer"], int)
    assert isinstance(data["dq_protest_window_minutes"], int)
    assert isinstance(data["min_recovery_minutes"], int)
    assert isinstance(data["timing_delta_threshold_cs"], int)
    assert data["scoring_tie_policy"] in ["SPLIT", "TOP"]
    assert data["status"] in [s.value for s in MeetStatus]


def assert_team(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meet_id", "")), "meet_id must be a UUID"
    assert isinstance(data["team_code"], str) and data["team_code"]
    assert isinstance(data["team_name"], str) and data["team_name"]
    assert data["status"] in [s.value for s in TeamStatus]
    assert isinstance(data["provisional_points"], (int, float))
    assert isinstance(data["official_points"], (int, float))
    assert isinstance(data["active_entry_count"], int)


def assert_swimmer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert data["gender"] in ["M", "F"]
    assert isinstance(data["age_on_meet_start"], int)
    assert data["age_group"] in [g.value for g in AgeGroup]
    assert data["status"] in [s.value for s in SwimmerStatus]


def assert_swim_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meet_id", "")), "meet_id must be a UUID"
    assert isinstance(data["event_number"], int)
    assert data["gender"] in ["M", "F", "MIXED"]
    assert data["age_group"] in [g.value for g in AgeGroup]
    assert data["stroke"] in [
        "FREESTYLE", "BACKSTROKE", "BREASTSTROKE", "BUTTERFLY",
        "INDIVIDUAL_MEDLEY", "FREESTYLE_RELAY", "MEDLEY_RELAY",
    ]
    assert isinstance(data["distance_meters"], int)
    assert isinstance(data["is_relay"], bool)
    assert data.get("qualifying_time_cs") is None or \
        isinstance(data["qualifying_time_cs"], int)
    assert isinstance(data["session_date"], str)
    assert isinstance(data["scheduled_start_minute"], int)
    assert isinstance(data["scheduled_end_minute"], int)
    assert data["scheduled_end_minute"] > data["scheduled_start_minute"]
    assert data["status"] in [s.value for s in SwimEventStatus]


def assert_event_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    has_swimmer = data.get("swimmer_id") is not None
    has_relay = data.get("relay_team_id") is not None
    assert has_swimmer != has_relay, \
        "exactly one of swimmer_id / relay_team_id must be populated"
    assert data.get("seed_time_cs") is None or isinstance(data["seed_time_cs"], int)
    assert data["qualification_status"] in [s.value for s in QualificationStatus]
    assert data["status"] in [s.value for s in EventEntryStatus]


def assert_relay_team(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert isinstance(data["relay_name"], str) and data["relay_name"]
    assert is_valid_uuid(data.get("entry_id", "")), \
        "entry_id must reference the auto-created EventEntry"
    assert data["status"] in [s.value for s in RelayTeamStatus]


def assert_relay_leg(data: dict):
    """Thin join record: only id + created_at plus the leg payload (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "relay leg must not carry updated_at"
    assert "version" not in data, "relay leg must not carry version"
    assert is_valid_uuid(data.get("relay_team_id", "")), \
        "relay_team_id must be a UUID"
    assert isinstance(data["leg_number"], int) and 1 <= data["leg_number"] <= 4
    assert is_valid_uuid(data.get("swimmer_id", "")), "swimmer_id must be a UUID"


def assert_lane_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a UUID"
    assert isinstance(data["heat_number"], int) and data["heat_number"] >= 1
    assert isinstance(data["lane_number"], int) and data["lane_number"] >= 1
    assert data["lane_status"] in [s.value for s in LaneStatus]
    for field in ("pad_cs", "backup1_cs", "backup2_cs", "watch_cs"):
        assert data.get(field) is None or isinstance(data[field], int), \
            f"{field} must be null or an integer count of centiseconds"
    assert data["pad_status"] in ["VALID", "INVALID", "UNKNOWN"]
    assert data["reconciliation_status"] in [s.value for s in ReconciliationStatus]
    assert data.get("reconciled_variant") is None or \
        data["reconciled_variant"] in [v.value for v in ReconciledVariant]
    assert data.get("final_time_cs") is None or isinstance(data["final_time_cs"], int)


def assert_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a UUID"
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert data["status"] in [s.value for s in ResultStatus]
    if data["status"] == ResultStatus.DQ_EXCLUDED.value:
        # PRD §3.9 pins null place and 0.00 points on every DQ_EXCLUDED row;
        # null final_time_cs is pinned only at direct creation, so it is not
        # asserted here (a rescore rewrite keeps the row's prior fields).
        assert data.get("place") is None, "DQ_EXCLUDED result has null place"
        assert data["points"] == 0 or data["points"] == 0.00, \
            "DQ_EXCLUDED result carries 0.00 points"
    else:
        assert isinstance(data["final_time_cs"], int)
        assert isinstance(data["place"], int) and data["place"] >= 1
        assert isinstance(data["points"], (int, float))


def assert_official(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meet_id", "")), "meet_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["lsc_membership_id"], str) and data["lsc_membership_id"]
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert in ["REFEREE", "STARTER", "STROKE_TURN_JUDGE", "CHIEF_TIMER"]
    assert isinstance(data["certification_expires_on"], str)


def assert_official_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("official_id", "")), "official_id must be a UUID"
    assert data["role_on_deck"] in \
        ["REFEREE", "STARTER", "STROKE_TURN_JUDGE", "CHIEF_TIMER"]
    assert data["status"] in [s.value for s in OfficialAssignmentStatus]


def assert_disqualification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lane_assignment_id", "")), \
        "lane_assignment_id must be a UUID"
    assert is_valid_uuid(data.get("reporting_official_id", "")), \
        "reporting_official_id must be a UUID"
    assert data.get("resolved_by_referee_id") is None or \
        is_valid_uuid(data["resolved_by_referee_id"])
    assert data["dq_code"] in [
        "FALSE_START", "FLY_ARMS_ALTERNATING", "BACK_FINISH_NOT_ON_BACK",
        "BR_KICK_DOWNWARD_WHIP", "IM_ORDER_VIOLATION", "TURN_NO_TOUCH",
        "RELAY_EARLY_TAKEOFF",
    ]
    assert isinstance(data["call_notes"], str)
    assert data["status"] in [s.value for s in DisqualificationStatus]
    assert data.get("notified_at") is None or \
        is_iso8601_timestamp(data["notified_at"])


def assert_meet_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert isinstance(data["record_time_cs"], int)
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["holder_team"], str) and data["holder_team"]
    assert isinstance(data["set_on_date"], str)
    assert data.get("challenger_entry_id") is None or \
        is_valid_uuid(data["challenger_entry_id"])
    assert data["status"] in [s.value for s in MeetRecordStatus]


def assert_points_precision(value, context="points"):
    """Every points figure renders with at most two decimal places (PRD §2.6)."""
    assert isinstance(value, (int, float)), f"{context} must be numeric"
    scaled = round(value * 100)
    assert abs(value * 100 - scaled) < 1e-9, \
        f"{context} must carry at most two decimal places, got {value}"
