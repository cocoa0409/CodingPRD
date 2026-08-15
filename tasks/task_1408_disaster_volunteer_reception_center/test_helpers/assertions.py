"""Entity assertions and domain invariant checkers.

Each assert_* validates the structural contract of one resource: server-minted
UUID id, ISO 8601 created_at/updated_at, integer version, and the fields the
PRD guarantees on the resource.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["lifecycle_status"] in ("ACTIVATION", "ACTIVE", "DEMOBILIZATION", "CLOSED")
    assert data["operational_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    stock = data["ppe_stock"]
    assert isinstance(stock, dict)
    assert set(stock.keys()) == {"GLOVES", "MASK", "HARD_HAT", "VEST", "GOGGLES"}
    for key, val in stock.items():
        assert isinstance(val, int) and val >= 0, f"ppe_stock[{key}] must be a non-negative integer"
    for field in ("provisional_cost_share_cents", "verified_cost_share_cents",
                  "federal_share_cents", "state_share_cents", "local_share_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_volunteer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", "")), "incident_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["home_locality"], str) and data["home_locality"]
    assert data["status"] in (
        "REGISTERED", "VETTING", "CLEARED", "READY", "DEPLOYED",
        "SUSPENDED", "DEMOBILIZED", "WITHDRAWN", "REJECTED",
    )
    assert isinstance(data.get("registered_by_user_id"), str)
    assert isinstance(data["committed_hours"], (int, float))
    assert isinstance(data["verified_hours_total"], (int, float))
    assert isinstance(data["current_risk_score"], int) and data["current_risk_score"] >= 0
    assert isinstance(data["lifetime_risk_score"], int) and data["lifetime_risk_score"] >= 0
    assert data["recognition_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")


def assert_credential(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["skill_code"] in (
        "GENERAL_LABOR", "CHAINSAW", "MEDICAL", "CDL", "SHELTER_OPS", "TRANSLATION",
    )
    assert data["credential_class"] in ("STANDARD", "ADVANCED")
    assert data["status"] in ("CLAIMED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_background_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in ("REQUESTED", "CLEARED", "FLAGGED", "EXPIRED")


def assert_clearance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["clearance_type"] in ("SAFETY_BRIEFING", "LIABILITY_WAIVER")
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("completed_at", ""))


def assert_support_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert isinstance(data["requesting_agency"], str) and data["requesting_agency"]
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert data["required_skill"] in (
        "GENERAL_LABOR", "CHAINSAW", "MEDICAL", "CDL", "SHELTER_OPS", "TRANSLATION",
    )
    assert data["min_credential_class"] in ("STANDARD", "ADVANCED")
    assert isinstance(data["headcount_needed"], int) and data["headcount_needed"] >= 1
    assert data["criticality"] in ("STANDARD", "CRITICAL")
    assert data["status"] in ("DRAFT", "OPEN", "MATCHING", "FILLED", "COMPLETED", "CANCELLED")
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert data["hazard_level"] in ("GREEN", "AMBER", "RED")
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["duration_hours"], (int, float)) and data["duration_hours"] >= 0.25
    assert isinstance(data["rostered_count"], int) and data["rostered_count"] >= 0
    assert data["status"] in ("SCHEDULED", "OPEN_FOR_ROSTER", "LOCKED", "CANCELLED")


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("support_request_id", ""))
    assert is_valid_uuid(data.get("site_shift_id", ""))
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "CONFIRMED", "CHECKED_IN", "COMPLETED",
        "CANCELLED", "DECLINED", "NO_SHOW", "RECALLED",
    )
    assert data["origin"] in ("MANUAL", "AUTO_MATCH")


def assert_trip(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert is_valid_uuid(data.get("site_shift_id", ""))
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert is_iso8601_timestamp(data.get("depart_at", ""))
    assert is_iso8601_timestamp(data.get("arrive_estimate_at", ""))
    assert isinstance(data["booked_seats"], int) and data["booked_seats"] >= 0
    assert data["status"] in ("SCHEDULED", "DEPARTED", "ARRIVED", "CANCELLED")


def assert_seat_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in ("BOOKED", "BOARDED", "NO_SHOW", "CANCELLED")


def assert_ppe_issuance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["item_type"] in ("GLOVES", "MASK", "HARD_HAT", "VEST", "GOGGLES")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("ISSUED", "RETURNED", "DAMAGED", "LOST")


def assert_hour_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["work_date"], str) and len(data["work_date"]) == 10
    assert isinstance(data["hours"], (int, float)) and 0 < data["hours"] <= 16
    assert data["status"] in ("SUBMITTED", "VERIFIED", "DISPUTED", "REJECTED_FINAL")
    assert isinstance(data.get("submitted_by_user_id"), str)
    assert isinstance(data["entry_value_cents"], int)
    assert isinstance(data["dispute_count"], int) and data["dispute_count"] >= 0
    assert isinstance(data["resubmit_count"], int) and data["resubmit_count"] >= 0


def assert_risk_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("subject_volunteer_id", ""))
    assert isinstance(data.get("reporter_user_id"), str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["category"] in ("SAFETY_VIOLATION", "MISCONDUCT", "NO_SHOW_PATTERN", "OTHER")
    assert data["status"] in ("FILED", "SUBSTANTIATED", "DISMISSED")


def assert_incident_share_invariants(data: dict):
    """The three reimbursement shares always sum back to the verified total,
    and the verified view never exceeds the provisional view."""
    assert data["federal_share_cents"] + data["state_share_cents"] + data["local_share_cents"] \
        == data["verified_cost_share_cents"]
    assert data["verified_cost_share_cents"] <= data["provisional_cost_share_cents"]


def assert_volunteer_risk_invariants(data: dict):
    """The lifetime score never decays, so it bounds the current score."""
    assert data["lifetime_risk_score"] >= data["current_risk_score"] >= 0
