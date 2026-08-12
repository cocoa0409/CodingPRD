"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating both 'Z' and offset spellings."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {type(value)}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 strings denote the same instant (serialization may differ)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    """Validate a Member response body against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["callsign"], str) and data["callsign"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["license_class"] in ("TECHNICIAN", "GENERAL", "EXTRA")
    assert is_iso8601_timestamp(data.get("license_expires_at", ""))
    assert data["membership_status"] in ("PENDING", "ACTIVE", "LAPSED", "SUSPENDED")
    if data.get("dues_paid_through") is not None:
        assert is_iso8601_timestamp(data["dues_paid_through"])
    assert data["equipment_privilege"] in ("GOOD_STANDING", "SUSPENDED")
    assert isinstance(data["readiness_score"], int)
    assert isinstance(data["readiness_score_optimistic"], int)
    assert data["readiness_tier"] in ("ELIGIBLE", "PROVISIONAL", "INELIGIBLE")
    for counter in ("check_ins_12m_count", "drills_12m_count", "no_shows_12m_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_member_invariants(data: dict):
    """Readiness invariants that must hold after any operation (PRD §2.8, §3.1)."""
    assert data["readiness_score"] >= 0, "verified score is floored at zero"
    assert data["readiness_score_optimistic"] >= 0, "optimistic score is floored at zero"
    score = data["readiness_score"]
    tier = data["readiness_tier"]
    if score >= 70:
        assert tier == "ELIGIBLE", f"score {score} must be ELIGIBLE, got {tier}"
    elif score >= 40:
        assert tier == "PROVISIONAL", f"score {score} must be PROVISIONAL, got {tier}"
    else:
        assert tier == "INELIGIBLE", f"score {score} must be INELIGIBLE, got {tier}"


def assert_antenna_site_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert is_iso8601_timestamp(data.get("lease_start", ""))
    assert is_iso8601_timestamp(data.get("lease_end", ""))
    assert data["status"] in ("NEGOTIATION", "ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_repeater(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["callsign"], str) and data["callsign"]
    assert isinstance(data["output_frequency_mhz"], (int, float))
    assert is_valid_uuid(data.get("site_agreement_id", ""))
    assert data["status"] in ("OPERATIONAL", "DEGRADED", "MAINTENANCE", "OFFLINE")


def assert_coordination_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repeater_id", ""))
    assert isinstance(data["requested_frequency_mhz"], (int, float))
    assert data["status"] in ("DRAFT", "SUBMITTED", "GRANTED", "RETURNED", "WITHDRAWN")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0


def assert_net_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("repeater_id", ""))
    assert is_valid_uuid(data.get("net_control_member_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["min_license_class"] in ("TECHNICIAN", "GENERAL", "EXTRA")
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["checkin_count"], int) and data["checkin_count"] >= 0


def assert_check_in(data: dict):
    """CheckIn is immutable: only id + created_at common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CheckIn must not carry a version field"
    assert "updated_at" not in data, "CheckIn must not carry an updated_at field"
    assert is_valid_uuid(data.get("net_session_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["has_traffic"], bool)
    assert isinstance(data["traffic_count"], int)
    assert is_iso8601_timestamp(data.get("checked_in_at", ""))


def assert_served_agency_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["max_operators"], int) and data["max_operators"] > 0
    assert is_iso8601_timestamp(data.get("effective_start", ""))
    assert is_iso8601_timestamp(data.get("effective_end", ""))
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")


def assert_emergency_activation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["required_operators"], int) and data["required_operators"] > 0
    assert data["status"] in ("STANDBY", "ACTIVATED", "DEMOBILIZED", "CANCELLED")
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["staffing_posture"] in ("UNDERSTAFFED", "ADEQUATE")


def assert_activation_invariants(data: dict):
    """Staffing threshold invariant (PRD §3.4): boundary is inclusive."""
    if data["confirmed_count"] >= data["required_operators"]:
        assert data["staffing_posture"] == "ADEQUATE"
    else:
        assert data["staffing_posture"] == "UNDERSTAFFED"


def assert_roster_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("activation_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["status"] in ("VOLUNTEERED", "CONFIRMED", "RELEASED", "WITHDRAWN", "NO_SHOW")


def assert_drill(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["passing_score"], int)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_drill_message(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drill_id", ""))
    assert is_valid_uuid(data.get("originator_member_id", ""))
    assert data["precedence"] in ("ROUTINE", "PRIORITY", "EMERGENCY")
    assert isinstance(data["relay_count"], int) and data["relay_count"] >= 0
    assert data["status"] in ("ORIGINATED", "RELAYED", "DELIVERED", "CANCELLED")
    if data["status"] == "DELIVERED":
        assert data.get("delivered_at") is not None
        assert isinstance(data.get("handling_seconds"), int)


def assert_field_day_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ("PLANNING", "OPEN", "SCORING", "FINALIZED")
    assert isinstance(data["contact_count"], int) and data["contact_count"] >= 0
    assert isinstance(data["provisional_score"], int) and data["provisional_score"] >= 0
    assert isinstance(data["final_score"], int) and data["final_score"] >= 0


def assert_field_day_contact(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("operator_member_id", ""))
    assert isinstance(data["worked_callsign"], str) and data["worked_callsign"]
    assert data["band"] in ("B160M", "B80M", "B40M", "B20M", "B15M", "B10M", "B6M", "B2M")
    assert data["mode"] in ("CW", "PHONE", "DIGITAL")
    assert data["power_category"] in ("QRP", "LOW", "HIGH")
    assert isinstance(data["is_duplicate"], bool)
    assert isinstance(data["points"], int) and 0 <= data["points"] <= 10


def assert_exam_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["location"], str) and data["location"]
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert isinstance(data["max_candidates"], int) and data["max_candidates"] > 0
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED", "CANCELLED")
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0


def assert_exam_candidate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data["candidate_name"], str) and data["candidate_name"]
    assert isinstance(data["frn"], str) and data["frn"]
    assert data["element"] in ("TECHNICIAN", "GENERAL", "EXTRA")
    assert data["status"] in ("REGISTERED", "CHECKED_IN", "PASSED", "FAILED", "NO_SHOW", "CANCELLED")


def assert_equipment_loan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_tag"], str) and data["item_tag"]
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["estimated_value_cents"], int) and data["estimated_value_cents"] > 0
    assert is_iso8601_timestamp(data.get("checked_out_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ("ACTIVE", "OVERDUE", "RETURNED", "LOST")
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    if data["status"] in ("ACTIVE", "OVERDUE"):
        assert data["late_fee_cents"] == 0, "late_fee_cents is zero while a loan is outstanding"
