"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_terminal(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["demurrage_daily_rate_cents"], int) and data["demurrage_daily_rate_cents"] >= 0
    assert isinstance(data["slot_capacity_per_window"], int) and data["slot_capacity_per_window"] >= 1


def assert_chassis(data: dict):
    _assert_common(data)
    assert isinstance(data["chassis_number"], str) and data["chassis_number"]
    assert isinstance(data["pool_scac"], str)
    assert isinstance(data["per_diem_rate_cents"], int) and data["per_diem_rate_cents"] >= 0
    assert isinstance(data["free_days"], int) and data["free_days"] >= 0
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "OUT")
    assert isinstance(data["per_diem_provisional_cents"], int) and data["per_diem_provisional_cents"] >= 0
    assert isinstance(data["per_diem_final_cents"], int) and data["per_diem_final_cents"] >= 0


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["container_number"], str) and data["container_number"]
    assert data["direction"] in ("IMPORT", "EXPORT")
    assert data["container_size"] in ("D20", "D40", "HC40")
    assert isinstance(data["origin_terminal_id"], str)
    assert isinstance(data["linehaul_base_cents"], int) and data["linehaul_base_cents"] >= 0
    assert isinstance(data["requires_permit"], bool)
    assert isinstance(data["demurrage_estimate_cents"], int) and data["demurrage_estimate_cents"] >= 0
    assert isinstance(data["demurrage_actual_cents"], int) and data["demurrage_actual_cents"] >= 0
    assert isinstance(data["per_diem_final_cents"], int) and data["per_diem_final_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "CHASSIS_ASSIGNED", "APPOINTED",
        "DISPATCHED", "DELIVERED", "EMPTY_RETURNED", "CANCELED",
    )


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["terminal_id"], str)
    assert data["purpose"] in ("PICKUP", "RETURN")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("BOOKED", "USED", "CANCELED")


def assert_leg(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["leg_type"] in ("PICKUP", "RETURN", "STREET_TURN")
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELED")


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["permit_number"], str)
    assert isinstance(data["max_gross_weight_lbs"], int) and data["max_gross_weight_lbs"] >= 0
    assert data["status"] in ("REQUESTED", "APPROVED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    for field in (
        "linehaul_base_cents", "effective_linehaul_cents", "fuel_surcharge_cents",
        "accessorials_total_cents", "demurrage_cents", "per_diem_cents", "total_charge_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative int"
    assert data["status"] in ("DRAFT", "ISSUED")


def assert_accessorial(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_id"], str)
    assert data["kind"] in ("CHASSIS_RENTAL", "PRE_PULL", "STORAGE", "HAZMAT", "REEFER")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_weigh_ticket(data: dict):
    """WeighTicket is immutable — only id + created_at, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["gross_weight_lbs"], int) and data["gross_weight_lbs"] >= 0
    assert isinstance(data["is_overweight"], bool)
