"""Entity assertions and domain invariant checkers (PRD-specific)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")
    assert data["insurance_status"] in ("NONE", "ACTIVE", "LAPSED")
    assert isinstance(data["total_charged_cents"], int)
    assert isinstance(data["total_credited_cents"], int)
    assert isinstance(data["balance_owed_cents"], int)
    assert isinstance(data["compliance_score"], int)
    # Money conservation invariant (Section 2.5).
    assert data["balance_owed_cents"] == data["total_charged_cents"] - data["total_credited_cents"], \
        "balance_owed_cents must equal total_charged_cents - total_credited_cents"
    # compliance_score is clamped to [0, 100].
    assert 0 <= data["compliance_score"] <= 100


def assert_commissary(data: dict):
    _assert_common(data)
    assert data["health_grade"] in ("A", "B", "C")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_cart(data: dict):
    _assert_common(data)
    assert data["cart_type"] in ("FOOD", "PRODUCE", "MERCHANDISE")
    assert data["status"] in ("PENDING", "APPROVED", "IMPOUNDED", "RETIRED")
    assert data["inspection_status"] in ("PENDING", "PASS", "FAIL")


def assert_zone(data: dict):
    _assert_common(data)
    assert data["zone_type"] in ("PRIME", "STANDARD")
    assert data["status"] in ("OPEN", "CLOSED")
    assert_zone_slot_conservation(data)


def assert_zone_slot_conservation(data: dict):
    """Slot conservation partition invariant (Section 2.6)."""
    assert data["assigned_slots"] >= 0, "assigned_slots must be non-negative"
    assert data["available_slots"] >= 0, "available_slots must be non-negative"
    assert data["assigned_slots"] + data["available_slots"] == data["capacity_slots"], \
        "assigned_slots + available_slots must equal capacity_slots"


def assert_spot(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "BLOCKED")


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ISSUED", "SUSPENDED", "REVOKED")
    assert data["permit_type"] in ("FOOD", "PRODUCE", "MERCHANDISE")
    assert isinstance(data["violation_points"], int)


def assert_lottery(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "DRAWN")


def assert_lottery_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENTERED", "AWARDED", "WAITLISTED")


def assert_spot_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert data["origin"] in ("DIRECT", "LOTTERY")


def assert_violation(data: dict):
    _assert_common(data)
    assert data["violation_type"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in ("ISSUED", "CONTESTED", "UPHELD", "DISMISSED")


def assert_impound(data: dict):
    _assert_common(data)
    assert data["reason"] in ("UNPERMITTED", "HEALTH_HAZARD", "ABANDONMENT", "SPACING")
    assert data["status"] in ("HELD", "RELEASED", "FORFEITED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["complaint_type"] in ("NOISE", "SANITATION", "BLOCKING", "UNPERMITTED")
    assert data["status"] in ("OPEN", "SUBSTANTIATED", "UNFOUNDED")
