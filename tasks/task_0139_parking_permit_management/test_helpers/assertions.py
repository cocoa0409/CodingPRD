"""Entity assertions and domain invariant checkers for Parking & Permit Management.

Each assert_{entity}() verifies the server-minted identity/timestamp shape and the
field types/enum membership the PRD guarantees. Append-only PlateRead is checked
WITHOUT updated_at/version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full-common-field entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_garage(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["gate_mode"] in ("PERMIT_OR_TRANSIENT", "PERMIT_ONLY", "CLOSED")
    assert isinstance(data["total_space_count"], int) and data["total_space_count"] >= 0
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0


def assert_zone(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert data["zone_type"] in ("TRANSIENT", "PERMIT", "MIXED")
    assert isinstance(data["permit_capacity"], int) and data["permit_capacity"] >= 0
    assert isinstance(data["permits_active_count"], int) and data["permits_active_count"] >= 0
    assert is_valid_uuid(data["rate_plan_id"])


def assert_space(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["label"], str) and data["label"]
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")
    assert isinstance(data["is_occupied"], bool)


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    for f in ("hourly_cents", "daily_cap_cents", "monthly_permit_cents", "grace_minutes"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_event_pricing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["flat_surcharge_cents"], int) and data["flat_surcharge_cents"] >= 0
    assert float(data["multiplier"]) >= 1.0
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["motorist_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["status"] in ("REQUESTED", "ACTIVE", "REVOKED", "EXPIRED", "REJECTED")
    assert isinstance(data["monthly_fee_charged_cents"], int)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["motorist_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["status"] in ("WAITING", "PROMOTED", "CANCELLED")
    assert isinstance(data["sequence"], int)


def assert_motorist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["default_plate"], str) and data["default_plate"]
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0


def assert_access_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert is_iso8601_timestamp(data["entry_at_utc"])
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    assert data["session_kind"] in ("PERMIT", "TRANSIENT")
    assert isinstance(data["gross_charge_cents"], int) and data["gross_charge_cents"] >= 0
    assert isinstance(data["net_charge_cents"], int) and data["net_charge_cents"] >= 0


def assert_validation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert data["discount_kind"] in ("FLAT_CENTS", "PERCENT", "FREE_HOURS")
    assert isinstance(data["discount_value"], int) and data["discount_value"] >= 0
    assert data["status"] in ("ISSUED", "REDEEMED")
    assert is_iso8601_timestamp(data["expires_at_utc"])


def assert_merchant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["validation_budget_cents"], int) and data["validation_budget_cents"] >= 0


def assert_citation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["garage_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert is_valid_uuid(data["plate_read_id"])
    assert data["violation_code"] in ("NO_PERMIT", "EXPIRED_PERMIT", "WRONG_ZONE", "OVERSTAY")
    assert isinstance(data["base_fine_cents"], int) and data["base_fine_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert isinstance(data["prior_citation_count"], int) and data["prior_citation_count"] >= 0
    assert data["status"] in ("ISSUED", "UPHELD", "DISMISSED", "PAID")


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["citation_id"])
    assert is_valid_uuid(data["motorist_id"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ("SUBMITTED", "UPHELD", "DISMISSED")


def assert_plate_read(data: dict):
    """PlateRead is append-only: only id + created_at, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PlateRead must not expose updated_at"
    assert "version" not in data, "PlateRead must not expose version"
    assert is_valid_uuid(data["garage_id"])
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["enforcement_outcome"] in (
        "COMPLIANT", "VIOLATION_NO_PERMIT", "VIOLATION_EXPIRED_PERMIT", "VIOLATION_WRONG_ZONE",
    )
