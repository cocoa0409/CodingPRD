"""Entity assertions and domain invariant checkers.

Every resource carries the common fields id/created_at/updated_at/version per
PRD "Common Resource Properties"; enum fields are checked against the value
sets named in the PRD prose.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, what: str):
    assert isinstance(data, dict), f"{what} must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{what}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{what}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{what}.version must be a positive integer"


def assert_event(data: dict):
    _assert_common(data, "Event")
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data.get("start_date", "")), \
        "Event.start_date must be an ISO 8601 timestamp"
    assert isinstance(data["has_swim"], bool)
    assert isinstance(data["water_pool_units"], int)
    assert isinstance(data["water_pool_remaining"], int)
    assert isinstance(data["appeal_window_minutes"], int)
    assert data["posture"] in [
        "DRAFT", "PERMITTED", "PUBLISHED", "LIVE", "FINALIZED", "CANCELLED",
    ]
    assert data["swim_status"] in [
        "PENDING_DECISION", "SWIM_ON", "SWIM_CANCELLED", "NO_SWIM",
    ]
    assert isinstance(data["ops_run_index"], int)


def assert_road_segment(data: dict):
    _assert_common(data, "RoadSegment")
    assert is_valid_uuid(data.get("event_id", "")), "RoadSegment.event_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["length_km"], (int, float))
    assert is_iso8601_timestamp(data.get("closure_start", ""))
    assert is_iso8601_timestamp(data.get("closure_end", ""))


def assert_course_permit(data: dict):
    _assert_common(data, "CoursePermit")
    assert is_valid_uuid(data.get("road_segment_id", ""))
    assert isinstance(data["authority_name"], str) and data["authority_name"]
    assert is_iso8601_timestamp(data.get("requested_start", ""))
    assert is_iso8601_timestamp(data.get("requested_end", ""))
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
    assert "rejection_reason" in data


def assert_wave(data: dict):
    _assert_common(data, "Wave")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["label"], str) and data["label"]
    assert data["division"] in ["AGE_GROUP", "ELITE"]
    assert is_iso8601_timestamp(data.get("scheduled_start_time", ""))
    assert "actual_start_time" in data
    assert isinstance(data["capacity"], int)
    assert isinstance(data["assigned_count"], int)
    assert isinstance(data["draft_legal"], bool)
    assert isinstance(data["age_band_min"], int)
    assert isinstance(data["age_band_max"], int)
    assert data["status"] in ["OPEN", "FULL", "CLOSED"]


def assert_athlete(data: dict):
    _assert_common(data, "Athlete")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str) and data["birth_date"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_status"] in ["ACTIVE", "SUSPENDED"]


def assert_registration(data: dict):
    _assert_common(data, "Registration")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert "wave_id" in data
    assert data["division"] in ["AGE_GROUP", "ELITE"]
    assert isinstance(data["entry_fee_cents"], int)
    assert "age_at_event" in data
    assert data["status"] in [
        "ENTERED", "PAID", "CONFIRMED", "WAITLISTED", "RACKED", "RACING",
        "FINISHED", "DNF", "DSQ", "WITHDRAWN", "EXPIRED",
    ]
    assert "refund_destination" in data
    assert "refund_estimate_cents" in data
    assert "refund_final_cents" in data
    assert "withdrawn_at" in data


def assert_bike_check(data: dict):
    _assert_common(data, "BikeCheck")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data["bib_code"], str) and data["bib_code"]
    assert data["status"] in ["CHECKED_IN", "CHECKED_OUT"]
    assert is_iso8601_timestamp(data.get("checked_in_at", ""))
    assert "checked_out_at" in data


def assert_aid_station(data: dict):
    _assert_common(data, "AidStation")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location_km"], (int, float))
    assert isinstance(data["required_volunteers"], int)
    assert isinstance(data["required_water_units"], int)
    assert isinstance(data["allocated_water_units"], int)
    assert isinstance(data["confirmed_volunteer_count"], int)
    assert data["readiness_status"] in ["UNDERSTAFFED", "WATER_SHORT", "READY"]


def assert_volunteer_assignment(data: dict):
    _assert_common(data, "VolunteerAssignment")
    assert is_valid_uuid(data.get("aid_station_id", ""))
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert is_iso8601_timestamp(data.get("shift_start", ""))
    assert is_iso8601_timestamp(data.get("shift_end", ""))
    assert data["status"] in ["OFFERED", "CONFIRMED", "NO_SHOW", "DECLINED"]


def assert_timing_record(data: dict):
    _assert_common(data, "TimingRecord")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["discipline"] in ["SWIM", "T1", "BIKE", "T2", "FINISH"]
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert data["status"] in ["RECORDED", "VALIDATED", "INVALIDATED"]


def assert_result(data: dict):
    _assert_common(data, "Result")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["status"] in ["PROVISIONAL", "OFFICIAL"]
    for split in ("swim_seconds", "t1_seconds", "bike_seconds",
                  "t2_seconds", "run_seconds"):
        assert split in data, f"Result missing split field {split}"
        assert data[split] is None or isinstance(data[split], int)
    assert isinstance(data["penalty_seconds_total"], int)
    assert "provisional_total_seconds" in data
    assert "official_total_seconds" in data
    assert "effective_total_seconds" in data
    assert "division_rank" in data
    assert "finish_timestamp" in data


def assert_penalty(data: dict):
    _assert_common(data, "Penalty")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["kind"] in ["DRAFTING", "COURSE_VIOLATION", "EQUIPMENT"]
    assert "notes" in data
    assert isinstance(data["seconds"], int)
    assert isinstance(data["triggers_dsq"], bool)
    assert data["status"] in ["ASSESSED", "CONFIRMED", "OVERTURNED"]
    assert isinstance(data["assessed_by_user_id"], str)
    assert is_iso8601_timestamp(data.get("assessed_at", ""))
    assert is_iso8601_timestamp(data.get("appeal_window_expires_at", ""))


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data.get("penalty_id", ""))
    assert isinstance(data["grounds"], str)
    assert data["status"] in ["FILED", "UNDER_REVIEW", "DECIDED"]
    assert "decision" in data
    assert "reduced_seconds" in data
    assert "decided_by_user_id" in data


def assert_safety_assessment(data: dict):
    _assert_common(data, "SafetyAssessment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["water_temp_celsius"], (int, float))
    assert isinstance(data["lightning_within_10km"], bool)
    assert data["outcome"] in ["SWIM_OK", "SWIM_CANCEL"]
    assert data["status"] in ["RECORDED", "SUPERSEDED"]


def assert_water_pool_invariant(event: dict, stations: list):
    """Conserved quantity: water_pool_remaining always equals water_pool_units
    minus the total allocated across the event's stations."""
    allocated = sum(s["allocated_water_units"] for s in stations)
    assert event["water_pool_remaining"] == event["water_pool_units"] - allocated, (
        f"water pool drift: remaining {event['water_pool_remaining']} != "
        f"{event['water_pool_units']} - {allocated}"
    )


def assert_wave_roster_invariant(wave: dict, registrations: list):
    """assigned_count equals the number of registrations pointing at the wave
    whose status is one of CONFIRMED, RACKED, RACING, FINISHED, DSQ."""
    holding = [
        r for r in registrations
        if r.get("wave_id") == wave["id"]
        and r.get("status") in {"CONFIRMED", "RACKED", "RACING", "FINISHED", "DSQ"}
    ]
    assert wave["assigned_count"] == len(holding), (
        f"wave roster drift: assigned_count {wave['assigned_count']} != "
        f"{len(holding)} slot-holding registrations"
    )
