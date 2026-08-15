"""Entity assertions and domain invariant checkers (PRD §2.4, §3.1)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_tour(data: dict):
    _assert_common(data, "Tour")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["PLANNING", "ON_TOUR", "COMPLETED", "CLOSED"]
    for f in ("budget_total_cents", "capitalization_cents", "per_diem_daily_cents",
              "royalty_tier_threshold_cents", "budget_committed_cents",
              "budget_spent_cents", "budget_available_cents",
              "cumulative_producer_net_cents", "royalty_accrued_cents"):
        assert isinstance(data[f], int), f"Tour.{f} must be an integer"
    assert data["per_diem_policy"] in ["FULL_WEEK", "ACTUAL_DAYS"]
    assert isinstance(data["recouped"], bool)


def assert_budget_identity(tour: dict):
    """PRD §3.1: available == total - committed - spent after every mutation."""
    total = tour["budget_total_cents"]
    committed = tour["budget_committed_cents"]
    spent = tour["budget_spent_cents"]
    available = tour["budget_available_cents"]
    assert committed + spent + available == total, (
        f"Budget identity broken: {committed} + {spent} + {available} != {total}"
    )


def assert_venue(data: dict):
    _assert_common(data, "Venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]
    for f in ("stage_width_ft", "fly_capacity_lines", "power_amps", "crew_available"):
        assert isinstance(data[f], int), f"Venue.{f} must be an integer"


def assert_stop(data: dict):
    _assert_common(data, "Stop")
    assert is_valid_uuid(data.get("tour_id", "")), "Stop.tour_id must be a UUID"
    assert is_valid_uuid(data.get("venue_id", "")), "Stop.venue_id must be a UUID"
    assert data["booking_status"] in ["TENTATIVE", "CONTRACTED", "ADVANCED", "READY",
                                      "PLAYING", "CLOSED", "WRAPPED", "CANCELLED"]
    assert data["compliance_status"] in ["PENDING", "IN_PROGRESS", "NON_COMPLIANT", "COMPLIANT"]
    assert isinstance(data["travel_in_days"], int) and data["travel_in_days"] >= 0
    assert isinstance(data["guarantee_cents"], int) and data["guarantee_cents"] >= 0


def assert_performance(data: dict):
    _assert_common(data, "Performance")
    assert is_valid_uuid(data.get("stop_id", "")), "Performance.stop_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "PLAYED", "CANCELLED"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_tech_check(data: dict):
    _assert_common(data, "TechRiderCheck")
    assert is_valid_uuid(data.get("stop_id", "")), "TechRiderCheck.stop_id must be a UUID"
    assert data["item"] in ["STAGE_WIDTH_FT", "FLY_LINES", "POWER_AMPS", "CREW_MINIMUM"]
    assert data["status"] in ["PENDING", "PASS", "FAIL", "WAIVED"]
    assert isinstance(data["required_value"], int) and data["required_value"] > 0


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert is_valid_uuid(data.get("stop_id", "")), "Settlement.stop_id must be a UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "DISPUTED", "APPROVED", "PAID", "VOID"]
    assert isinstance(data["system_gross_cents"], int)


def assert_cast_member(data: dict):
    _assert_common(data, "CastMember")
    assert is_valid_uuid(data.get("tour_id", "")), "CastMember.tour_id must be a UUID"
    assert data["contract_type"] in ["PRINCIPAL", "UNDERSTUDY", "SWING", "ENSEMBLE"]
    assert data["status"] in ["OFFERED", "CONTRACTED", "ON_LEAVE", "REPLACED", "RELEASED"]
    assert isinstance(data["weekly_salary_cents"], int) and data["weekly_salary_cents"] > 0
    assert isinstance(data["bump_shows_accrued"], int)
    assert isinstance(data["bump_pay_cents"], int)


def assert_track(data: dict):
    _assert_common(data, "CharacterTrack")
    assert is_valid_uuid(data.get("tour_id", "")), "CharacterTrack.tour_id must be a UUID"
    assert isinstance(data["track_name"], str) and data["track_name"]
    assert isinstance(data["required_covers"], int) and data["required_covers"] >= 0
    assert isinstance(data["available_covers"], int)
    assert isinstance(data["exposed"], bool)


def assert_coverage(data: dict):
    _assert_common(data, "CoverageAssignment")
    assert is_valid_uuid(data.get("track_id", "")), "CoverageAssignment.track_id must be a UUID"
    assert is_valid_uuid(data.get("cast_member_id", "")), "CoverageAssignment.cast_member_id must be a UUID"
    assert data["kind"] in ["UNDERSTUDY", "SWING"]
    assert data["status"] in ["STANDBY", "ACTIVATED", "SUSPENDED", "RELEASED"]
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1


def assert_injury(data: dict):
    _assert_common(data, "InjuryEvent")
    assert is_valid_uuid(data.get("cast_member_id", "")), "InjuryEvent.cast_member_id must be a UUID"
    assert data["status"] in ["COVERED", "RESOLVED", "REPLACED"]


def assert_per_diem(data: dict):
    _assert_common(data, "PerDiemStatement")
    assert is_valid_uuid(data.get("stop_id", "")), "PerDiemStatement.stop_id must be a UUID"
    assert is_valid_uuid(data.get("cast_member_id", "")), "PerDiemStatement.cast_member_id must be a UUID"
    assert data["policy_snapshot"] in ["FULL_WEEK", "ACTUAL_DAYS"]
    assert data["status"] in ["ISSUED", "PAID"]
    assert 1 <= data["days_present"] <= 7
    assert isinstance(data["total_cents"], int)


def assert_crew_call(data: dict):
    _assert_common(data, "CrewCall")
    assert is_valid_uuid(data.get("stop_id", "")), "CrewCall.stop_id must be a UUID"
    assert data["call_type"] in ["LOAD_IN", "LOAD_OUT", "SHOW_RUN"]
    assert data["status"] in ["POSTED", "SETTLED", "CANCELLED"]
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
