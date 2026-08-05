"""Entity assertions and domain invariant checkers (PRD Sections 2.5, 3).

Each ``assert_{entity}`` validates the response shape against the PRD contract;
they use the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields (PRD Section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_community(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["resident_type"] in ("OWNER", "TENANT")
    assert isinstance(data["directory_listed"], bool)
    assert data["callbox_code"] is not None and str(data["callbox_code"]) != ""
    assert data["status"] in ("ACTIVE", "SUSPENDED", "MOVED_OUT")
    assert data["standing"] in ("GOOD", "DELINQUENT")
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["plate"], str) and data["plate"]
    assert isinstance(data["plate_state"], str) and data["plate_state"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_decal(data: dict):
    _assert_common(data)
    assert isinstance(data["vehicle_id"], str)
    assert data["tier"] in ("RESIDENT", "TENANT", "TEMPORARY")
    assert data["decal_number"] is not None and str(data["decal_number"]) != ""
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_pass(data: dict):
    _assert_common(data)
    assert isinstance(data["sponsor_resident_id"], str)
    assert data["pass_type"] in ("GUEST", "VENDOR")
    assert isinstance(data["visitor_name"], str) and data["visitor_name"]
    assert isinstance(data["visitor_plate"], str) and data["visitor_plate"]
    assert data["auth_status"] in ("PENDING", "APPROVED", "DENIED", "REVOKED", "EXPIRED")
    assert data["presence_status"] in ("OFFSITE", "ONSITE", "DEPARTED")


def assert_gate_event(data: dict):
    """Append-only log (PRD Section 2.5): id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "GateEvent must not expose updated_at"
    assert "version" not in data, "GateEvent must not expose version"
    assert data["direction"] in ("ENTRY", "EXIT")
    assert data["matched_type"] in ("DECAL", "PASS", "UNMATCHED")
    assert data["decision"] in ("ALLOW", "DENY")


def assert_amenity(data: dict):
    _assert_common(data)
    assert data["amenity_type"] in ("POOL", "GYM", "CLUBHOUSE", "TENNIS")
    assert data["capacity"] >= 1
    assert data["hourly_fee_cents"] >= 0
    assert data["deposit_cents"] >= 0
    assert isinstance(data["reservable"], bool)


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["amenity_id"], str)
    assert isinstance(data["resident_id"], str)
    assert data["party_size"] >= 1
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["quoted_fee_cents"], int)


def assert_patrol(data: dict):
    _assert_common(data)
    assert isinstance(data["officer_id"], str)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_incident(data: dict):
    _assert_common(data)
    assert data["incident_type"] in (
        "TRESPASS", "NOISE", "SPEEDING", "VANDALISM", "UNAUTHORIZED_ACCESS", "OTHER",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("REPORTED", "INVESTIGATING", "RESOLVED", "CLOSED")


def assert_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert data["violation_type"] in (
        "SPEEDING", "NOISE", "PARKING", "UNAUTHORIZED_GUEST", "GATE_TAILGATING",
    )
    assert isinstance(data["assessed_fine_cents"], int)
    assert isinstance(data["repeat_index"], int)
    assert data["status"] in (
        "ISSUED", "APPEALED", "UPHELD", "DISMISSED", "REDUCED", "PAID", "VOID",
    )
