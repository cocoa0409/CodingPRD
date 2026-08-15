"""Entity assertions and domain invariant helpers (PRD sections 2.2-2.4 and 3)."""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

__all__ = [
    "assert_season",
    "assert_race_class",
    "assert_driver",
    "assert_kart",
    "assert_event",
    "assert_entry",
    "assert_session",
    "assert_session_result",
    "assert_inspection",
    "assert_incident",
    "assert_booking",
    "standings_row_for",
]


def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """PRD 2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_season(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LeagueSeason")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["year"], int)
    assert isinstance(data["drop_rounds"], int) and data["drop_rounds"] >= 0
    assert isinstance(data["points_scheme"], list)
    assert all(isinstance(p, int) for p in data["points_scheme"])
    assert isinstance(data["fastest_lap_bonus_points"], int)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "FINALIZED", "AWARDS_CONCLUDED"]
    assert isinstance(data["rounds_completed"], int) and data["rounds_completed"] >= 0
    assert isinstance(data["collected_fees_cents"], int)
    assert data["collected_fees_cents"] >= 0


def assert_race_class(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RaceClass")
    assert data["code"] in ["CADET", "JUNIOR", "SENIOR", "HEAVY"]
    assert isinstance(data["min_age"], int)
    assert isinstance(data["max_age"], int)
    assert isinstance(data["min_combined_weight_kg"], (int, float))
    assert data["min_combined_weight_kg"] > 0
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert isinstance(data["rental_kart_allowed"], bool)
    assert data.get("season_id"), "RaceClass must echo its parent season_id"


def assert_driver(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Driver")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["body_weight_kg"], (int, float))
    assert data["body_weight_kg"] > 0
    assert data["license_type"] in ["RENTAL", "OWNER"]
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED"]


def assert_kart(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RentalKart")
    assert isinstance(data["fleet_number"], str) and data["fleet_number"]
    assert isinstance(data["eligible_class_codes"], list)
    assert data["status"] in ["AVAILABLE", "IN_MAINTENANCE", "RETIRED"]


def assert_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RaceEvent")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["event_date"], str) and data["event_date"]
    assert isinstance(data["track_name"], str) and data["track_name"]
    assert data["status"] in [
        "SCHEDULED",
        "REGISTRATION_OPEN",
        "IN_PROGRESS",
        "COMPLETED",
        "FINALIZED",
        "CANCELLED",
    ]
    assert data.get("season_id"), "RaceEvent must echo its parent season_id"


def assert_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "EventEntry")
    assert data.get("event_id"), "EventEntry must echo its parent event_id"
    assert data.get("driver_id")
    assert data.get("class_id")
    assert data["entry_type"] in ["RENTAL", "OWNER_DRIVER"]
    assert data["status"] in [
        "ENTERED",
        "TECH_CHECK",
        "TECH_FAILED",
        "TECH_PASSED",
        "GRID_LOCKED",
        "WITHDRAWN",
        "DISQUALIFIED",
    ]
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert data["fee_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert isinstance(data["tech_fail_count"], int) and data["tech_fail_count"] >= 0
    assert isinstance(data["event_points"], int) and data["event_points"] >= 0


def assert_session(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RaceSession")
    assert data.get("event_id"), "RaceSession must echo its parent event_id"
    assert data["session_type"] in ["PRACTICE", "QUALIFYING", "HEAT", "MAIN"]
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "SCORED"]


def assert_session_result(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SessionResult")
    assert data.get("session_id"), "SessionResult must echo its parent session_id"
    assert data.get("entry_id")
    assert isinstance(data["finish_position"], int) and data["finish_position"] >= 1
    assert isinstance(data["best_lap_ms"], int) and data["best_lap_ms"] > 0
    assert isinstance(data["total_time_ms"], int) and data["total_time_ms"] > 0
    assert isinstance(data["penalty_seconds_applied"], int)
    assert data["penalty_seconds_applied"] >= 0
    assert isinstance(data["is_fastest_lap"], bool)
    assert isinstance(data["points_awarded"], int) and data["points_awarded"] >= 0
    assert data["status"] in ["PROVISIONAL", "AMENDED", "FINAL"]


def assert_inspection(data: Dict[str, Any]) -> None:
    """PRD 2.4: an inspection record is append-only and carries only id and
    created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "TechInspection.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TechInspection.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "TechInspection must not carry updated_at"
    assert "version" not in data, "TechInspection must not carry version"
    assert data.get("entry_id")
    assert isinstance(data["measured_combined_weight_kg"], (int, float))
    assert data["measured_combined_weight_kg"] > 0
    assert data["outcome"] in ["PASS", "FAIL"]
    assert isinstance(data.get("inspector_user_id"), str)


def assert_incident(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Incident")
    assert data.get("event_id"), "Incident must echo its parent event_id"
    assert data.get("entry_id")
    assert data.get("session_id")
    assert isinstance(data["description"], str)
    assert isinstance(data["reporter_user_id"], str) and data["reporter_user_id"]
    assert data["status"] in [
        "REPORTED",
        "UNDER_REVIEW",
        "UPHELD",
        "DISMISSED",
        "APPEALED",
    ]
    assert data.get("penalty_kind") in (None, "NONE", "TIME_SECONDS", "DISQUALIFICATION")
    assert data.get("penalty_seconds") is None or (
        isinstance(data["penalty_seconds"], int) and data["penalty_seconds"] > 0
    )
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 1


def assert_booking(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PracticeBooking")
    assert data.get("driver_id")
    assert data.get("kart_id")
    assert isinstance(data["start_time"], str) and data["start_time"]
    assert isinstance(data["end_time"], str) and data["end_time"]
    assert data["pricing_mode"] in ["FLAT", "METERED"]
    assert data["status"] in ["RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED"]
    assert data.get("minutes_used") is None or isinstance(data["minutes_used"], int)
    assert data.get("fee_cents") is None or isinstance(data["fee_cents"], int)


def standings_row_for(standings: Dict[str, Any], driver_id: str) -> Dict[str, Any]:
    """Return the standings row for one driver from a standings response payload."""
    for row in standings["rows"]:
        if row.get("driver_id") == driver_id:
            return row
    raise AssertionError(
        f"driver {driver_id} missing from standings rows: {standings['rows']}"
    )
