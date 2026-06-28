"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

BOOKING_STATES = ["REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_SERVICE",
                  "COMPLETED", "CANCELLED", "NO_SHOW"]
PAYMENT_STATES = ["UNPAID", "DEPOSIT_HELD", "SETTLED", "REFUNDED", "FORFEITED"]


def _assert_common(data: dict):
    """Common four-field set for entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only entities carry ONLY id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["pay_model"] in ("COMMISSION", "BOOTH_RENT")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["accrued_earnings_cents"], int)
    assert isinstance(data["lifetime_no_show_strikes_attributed"], int)


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["requires_autoclave"], bool)
    assert data["sanitation_status"] in ("CLEAN", "DIRTY")


def assert_sanitation_log(data: dict):
    _assert_append_only(data)
    assert "updated_at" not in data, "append-only SanitationLog must not carry updated_at"
    assert "version" not in data, "append-only SanitationLog must not carry version"
    assert data["cycle_result"] in ("PASS", "FAIL")


def assert_menu_item(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("MANICURE", "PEDICURE", "ENHANCEMENT")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 5
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_add_on(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["active_no_show_strikes"], int)
    assert isinstance(data["deposit_required"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["booking_status"] in BOOKING_STATES
    assert data["payment_status"] in PAYMENT_STATES
    assert data["origin"] in ("WALK_IN", "APPOINTMENT")
    assert isinstance(data["deposit_due_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_charged_cents"], int)


def assert_appointment_add_on(data: dict):
    _assert_append_only(data)
    assert "updated_at" not in data, "append-only AppointmentAddOn must not carry updated_at"
    assert "version" not in data, "append-only AppointmentAddOn must not carry version"


def assert_gift_card(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "DEPLETED", "VOID")


def assert_commission_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SETTLED", "VOID")
    assert isinstance(data["gross_service_cents"], int)
    assert isinstance(data["technician_payout_cents"], int)
    assert isinstance(data["salon_retained_cents"], int)
    assert isinstance(data["swept_appointment_count"], int)
