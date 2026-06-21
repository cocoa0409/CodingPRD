"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_hotel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["current_business_date"], str)
    assert data["posture"] in ("OPEN", "AUDIT_LOCK")
    assert isinstance(data["audit_epoch"], int) and data["audit_epoch"] >= 0
    assert isinstance(data["overbooking_allowance_pct"], (int, float))


def assert_room_type(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["code"], str)
    assert isinstance(data["tier_rank"], int)
    assert isinstance(data["physical_inventory"], int)
    assert isinstance(data["base_rate_cents"], int)


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["room_type_id"], str)
    assert isinstance(data["room_number"], str)
    assert data["housekeeping_status"] in (
        "DIRTY", "CLEAN", "INSPECTED", "OCCUPIED", "OUT_OF_ORDER",
    )


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert data["kind"] in ("BAR", "CORPORATE", "PACKAGE")
    assert data["adjustment_mode"] in ("PCT", "FLAT")
    assert data["no_show_policy"] in ("FIRST_NIGHT", "FULL_STAY", "NONE")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_corporate_account(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["loyalty_tier"] in ("NONE", "SILVER", "GOLD", "PLATINUM")


def assert_group_block(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["room_type_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert isinstance(data["blocked_rooms"], int)
    assert isinstance(data["picked_up_rooms"], int)
    assert isinstance(data["washed_rooms"], int)
    assert data["status"] in ("OPEN", "WASHED", "CLOSED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["guest_id"], str)
    assert isinstance(data["room_type_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert isinstance(data["arrival_date"], str)
    assert isinstance(data["departure_date"], str)
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["is_upgraded"], bool)
    assert isinstance(data["upgrade_is_comp"], bool)
    assert data["status"] in (
        "HELD", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW",
    )


def assert_folio(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["reservation_id"], str)
    assert isinstance(data["room_charges_cents"], int)
    assert isinstance(data["projected_charges_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["bill_to"] in ("GUEST", "CORPORATE")
    assert data["status"] in ("OPEN", "CLOSED", "DISPUTED")


def assert_incidental(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["folio_id"], str)
    assert data["kind"] in ("CHARGE", "PAYMENT", "ADJUSTMENT")
    assert isinstance(data["amount_cents"], int)
    assert data["posted_by_kind"] in ("AGENT", "NIGHT_AUDIT")
    assert data["status"] in ("POSTED", "VOIDED")


def assert_night_audit_run(data: dict):
    _assert_common(data)
    assert isinstance(data["hotel_id"], str)
    assert isinstance(data["business_date"], str)
    assert data["status"] in ("IN_PROGRESS", "COMPLETED", "ABORTED")


def assert_availability_cell(data: dict):
    """Availability cells carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["stay_date"], str)
    assert isinstance(data["sold_count"], int)
    assert isinstance(data["sellable_count"], int)
    assert "version" not in data, "availability cell must not carry version"
    assert "updated_at" not in data, "availability cell must not carry updated_at"
