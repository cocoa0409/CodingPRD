"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Versioned entities carry id/created_at/updated_at/
version; Permit and CatchReport are write-once and carry only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CHARTER_STATES = {"DRAFT", "SCHEDULED", "WEATHER_HOLD", "SAILED", "SETTLED", "CANCELLED"}
_BOOKING_STATES = {"RESERVED", "CONFIRMED", "CANCELLED", "SETTLED", "NO_SHOW"}
_CREW_STATES = {"TENTATIVE", "LOCKED", "RELEASED"}
_RES_STATES = {"HELD", "OCCUPIED", "RELEASED"}
_ADDON_STATES = {"PENDING", "FULFILLED", "VOIDED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_marina(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["status"] in {"OPEN", "RESTRICTED", "CLOSED"}
    assert isinstance(data["open_slot_count"], int) and data["open_slot_count"] >= 0


def assert_dock_slot(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["marina_id"])
    assert isinstance(data["slot_label"], str) and len(data["slot_label"]) > 0
    assert data["status"] in {"ACTIVE", "DECOMMISSIONED"}


def assert_boat(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["marina_id"])
    assert data["length_ft"] > 0
    assert isinstance(data["passenger_capacity"], int) and data["passenger_capacity"] >= 1
    assert isinstance(data["offshore_rated"], bool)
    assert data["status"] in {"IN_SERVICE", "DRYDOCK"}


def assert_captain(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["marina_id"])
    assert data["uscg_license_grade"] in {"OUPV", "MASTER_50", "MASTER_100"}
    assert data["status"] in {"AVAILABLE", "SUSPENDED"}


def assert_mate(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["marina_id"])
    assert isinstance(data["certified_offshore"], bool)
    assert data["status"] in {"AVAILABLE", "SUSPENDED"}


def assert_permit(data: dict):
    """Permit is write-once (PRD §2.4): no updated_at, no version."""
    _assert_common(data)
    assert "version" not in data, "Permit must NOT carry a version field"
    assert "updated_at" not in data, "Permit must NOT carry an updated_at field"
    assert data["permit_kind"] in {"FEDERAL_OFFSHORE", "STATE_INSHORE"}
    assert isinstance(data["daily_bag_limit"], int) and data["daily_bag_limit"] >= 0


def assert_customer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["loyalty_tier"] in {"STANDARD", "SILVER", "GOLD"}


def assert_charter(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["marina_id"])
    assert is_valid_uuid(data["boat_id"])
    assert data["trip_type"] in {"INSHORE", "OFFSHORE", "HALF_DAY"}
    assert is_iso8601_timestamp(data["depart_at"])
    assert is_iso8601_timestamp(data["return_at"])
    assert isinstance(data["base_seat_price_cents"], int) and data["base_seat_price_cents"] >= 0
    assert isinstance(data["seats_total"], int)
    assert isinstance(data["seats_booked"], int) and data["seats_booked"] >= 0
    assert data["seats_booked"] <= data["seats_total"], "seats_booked never exceeds seats_total"
    assert isinstance(data["catch_total"], int) and data["catch_total"] >= 0
    assert isinstance(data["weather_reschedule_count"], int) and data["weather_reschedule_count"] >= 0
    assert data["status"] in _CHARTER_STATES


def assert_slot_reservation(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["dock_slot_id"])
    assert is_valid_uuid(data["charter_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in _RES_STATES


def assert_crew_assignment(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["charter_id"])
    assert data["role_slot"] in {"CAPTAIN", "MATE"}
    assert data["status"] in _CREW_STATES


def assert_booking(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["charter_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["seat_subtotal_cents"], int) and data["seat_subtotal_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert data["gratuity_input_mode"] in {"PERCENT", "FLAT"}
    assert isinstance(data["gratuity_cents"], int) and data["gratuity_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["reschedule_fee_total_cents"], int) and data["reschedule_fee_total_cents"] >= 0
    assert isinstance(data["weather_waiver"], bool)
    assert data["status"] in _BOOKING_STATES


def assert_add_on_line(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["addon_kind"] in {"BAIT", "ROD_RENTAL", "FISH_CLEANING", "COOLER_ICE"}
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0
    assert data["status"] in _ADDON_STATES


def assert_catch_report(data: dict):
    """CatchReport is write-once (PRD §2.4): no updated_at, no version."""
    _assert_common(data)
    assert "version" not in data, "CatchReport must NOT carry a version field"
    assert "updated_at" not in data, "CatchReport must NOT carry an updated_at field"
    assert is_valid_uuid(data["charter_id"])
    assert isinstance(data["fish_count"], int) and data["fish_count"] >= 1
    assert isinstance(data["released_count"], int) and 0 <= data["released_count"] <= data["fish_count"]
