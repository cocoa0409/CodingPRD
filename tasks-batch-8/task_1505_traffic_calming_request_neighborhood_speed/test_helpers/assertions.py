"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BallotStatus,
    CycleStatus,
    EmergencyReviewStatus,
    FunctionalClass,
    PlanStatus,
    RemovalStatus,
    RequestStatus,
    ScheduleStatus,
    StudyStatus,
    StudyType,
    TreatmentType,
    VoteChoice,
)


def parse_logical_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"Not a valid ISO 8601 UTC timestamp: {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_timestamp_equals(value: str, expected_iso: str, label: str = ""):
    """Assert a system-stamped timestamp equals an expected logical instant,
    independent of fractional-digit formatting."""
    actual = parse_logical_ts(value)
    expected = parse_logical_ts(expected_iso)
    assert actual == expected, (
        f"{label or 'timestamp'} must equal {expected_iso}, got {value}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_event_record(data: dict, entity: str):
    """PRD §2.5: petition signatures, study observations and ballot votes are
    immutable event records carrying only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_segment(data: dict):
    _assert_common_fields(data, "StreetSegment")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["speed_limit_mph"], int) and data["speed_limit_mph"] >= 15
    assert isinstance(data["household_count"], int) and data["household_count"] >= 1
    assert data["functional_class"] in [c.value for c in FunctionalClass]
    assert isinstance(data["emergency_route"], bool)
    assert isinstance(data["crash_count_3yr"], int) and data["crash_count_3yr"] >= 0
    assert isinstance(data["pedestrian_generator_count"], int)
    assert data["pedestrian_generator_count"] >= 0


def assert_resident(data: dict):
    _assert_common_fields(data, "Resident")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data.get("street_segment_id", ""))
    assert isinstance(data["household_ref"], str) and data["household_ref"]


def assert_request(data: dict):
    _assert_common_fields(data, "TrafficCalmingRequest")
    assert is_valid_uuid(data.get("street_segment_id", ""))
    assert isinstance(data.get("created_by_resident_id"), str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["requested_budget_cents"], int)
    assert data["requested_budget_cents"] > 0
    assert data["status"] in [s.value for s in RequestStatus]


def assert_signature(data: dict):
    _assert_event_record(data, "PetitionSignature")
    assert is_valid_uuid(data.get("request_id", ""))
    assert isinstance(data.get("resident_id"), str) and data["resident_id"]
    assert isinstance(data.get("household_ref"), str) and data["household_ref"]
    assert is_iso8601_timestamp(data.get("signed_at", ""))


def assert_study(data: dict):
    _assert_common_fields(data, "SpeedStudy")
    assert is_valid_uuid(data.get("request_id", ""))
    assert data["study_type"] in [t.value for t in StudyType]
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert data["status"] in [s.value for s in StudyStatus]


def assert_observation(data: dict):
    _assert_event_record(data, "StudyObservation")
    assert is_valid_uuid(data.get("study_id", ""))
    assert isinstance(data["observation_date"], str)
    assert isinstance(data["vehicle_count"], int) and data["vehicle_count"] >= 0
    assert data["p85_speed_mph"] > 0
    assert data["mean_speed_mph"] > 0
    assert isinstance(data["is_valid"], bool)


def assert_cycle(data: dict):
    _assert_common_fields(data, "FundingCycle")
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["budget_total_cents"], int)
    assert data["budget_total_cents"] > 0
    assert isinstance(data["budget_committed_cents"], int)
    assert data["budget_committed_cents"] >= 0
    assert isinstance(data["budget_available_cents"], int)
    assert data["status"] in [s.value for s in CycleStatus]


def assert_cycle_budget_invariant(data: dict):
    """PRD §3.4: budget_available_cents is always the total minus committed."""
    assert (
        data["budget_committed_cents"] + data["budget_available_cents"]
        == data["budget_total_cents"]
    ), (
        f"cycle budget invariant broken: {data['budget_committed_cents']} + "
        f"{data['budget_available_cents']} != {data['budget_total_cents']}"
    )


def assert_plan(data: dict):
    _assert_common_fields(data, "TreatmentPlan")
    assert is_valid_uuid(data.get("request_id", ""))
    assert data["treatment_type"] in [t.value for t in TreatmentType]
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] > 0
    assert isinstance(data["created_by_user_id"], str)
    assert data["created_by_user_id"]
    assert data["status"] in [s.value for s in PlanStatus]


def assert_ballot(data: dict):
    _assert_common_fields(data, "Ballot")
    assert is_valid_uuid(data.get("request_id", ""))
    assert isinstance(data.get("treatment_plan_id"), str)
    assert isinstance(data.get("close_date"), str)
    assert isinstance(data["eligible_households"], int)
    assert data["eligible_households"] >= 1
    assert isinstance(data["quorum_required"], int) and data["quorum_required"] >= 1
    assert isinstance(data["votes_received"], int) and data["votes_received"] >= 0
    assert isinstance(data["votes_for"], int) and data["votes_for"] >= 0
    assert isinstance(data["votes_against"], int) and data["votes_against"] >= 0
    assert data["status"] in [s.value for s in BallotStatus]
    assert data.get("outcome") in (None, "CONSENT_GRANTED", "CONSENT_DENIED")


def assert_vote(data: dict):
    _assert_event_record(data, "BallotVote")
    assert is_valid_uuid(data.get("ballot_id", ""))
    assert isinstance(data.get("resident_id"), str) and data["resident_id"]
    assert isinstance(data.get("household_ref"), str) and data["household_ref"]
    assert data["choice"] in [c.value for c in VoteChoice]
    assert is_iso8601_timestamp(data.get("cast_at", ""))


def assert_work_order(data: dict):
    _assert_common_fields(data, "InstallationWorkOrder")
    assert is_valid_uuid(data.get("request_id", ""))
    assert isinstance(data["crew_ref"], str) and data["crew_ref"]
    assert data["schedule_status"] in [s.value for s in ScheduleStatus]
    assert data["emergency_review_status"] in [
        s.value for s in EmergencyReviewStatus
    ]


def assert_removal_request(data: dict):
    _assert_common_fields(data, "RemovalRequest")
    assert is_valid_uuid(data.get("request_id", ""))
    assert isinstance(data.get("created_by_resident_id"), str)
    assert isinstance(data["reason"], str)
    assert data["status"] in [s.value for s in RemovalStatus]
