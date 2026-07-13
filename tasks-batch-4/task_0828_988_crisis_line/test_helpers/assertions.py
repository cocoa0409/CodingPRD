"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["channel"] in ["PHONE", "CHAT", "TEXT"]
    assert isinstance(data["caller_key"], str) and len(data["caller_key"]) > 0
    assert data["status"] in [
        "INTAKE", "SCREENED", "DE_ESCALATION", "DISPATCH_PENDING",
        "REFERRAL_PENDING", "EMERGENCY_911", "RESOLVED", "CLOSED",
    ]
    assert data["emergency_status"] in ["NONE", "INITIATED"]
    assert isinstance(data["has_active_safety_plan"], bool)
    assert isinstance(data["version"], int)


def assert_risk_screening(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["screening_type"] in ["PROVISIONAL", "COMPREHENSIVE"]
    assert isinstance(data["risk_score"], int)
    assert data["risk_band"] in ["LOW", "MODERATE", "HIGH", "IMMINENT"]


def assert_crisis_center(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ONLINE", "DIVERTED"]
    assert isinstance(data["bed_capacity"], int)
    assert_center_ledger(data)


def assert_center_ledger(data: dict):
    """Conserved bed ledger invariant (PRD §2.9)."""
    assert data["held_beds"] >= 0
    assert data["occupied_beds"] >= 0
    assert (
        data["available_beds"] + data["held_beds"] + data["occupied_beds"]
        == data["bed_capacity"]
    ), "available + held + occupied must equal bed_capacity"


def assert_team_slot_ledger(data: dict):
    """Conserved team slot invariant (PRD §2.9)."""
    assert data["active_dispatch_count"] >= 0
    assert data["active_dispatch_count"] <= data["capacity"], (
        "active_dispatch_count must never exceed capacity"
    )


def assert_emergency_coordination(data: dict):
    """EmergencyCoordination is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["risk_band_at_escalation"] in ["LOW", "MODERATE", "HIGH", "IMMINENT"]
