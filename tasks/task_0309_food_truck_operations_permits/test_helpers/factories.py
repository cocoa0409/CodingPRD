"""Payload factories — one per entity, input fields only.

Each factory returns the request body for a create / action call. Computed and
system-managed fields are never included; tests override only what they control.
"""

DEFAULTS = {
    "COMMISSARY_NAME": "Central Kitchen",
    "TRUCK_NAME": "Test Truck",
    "STATE_CODE": "CA",
    "PERMIT_NUMBER": "P-TEST",
    "ISSUED_AT": "2026-05-01T00:00:00.000Z",
    "EXPIRES_AT": "2026-12-01T00:00:00.000Z",
    "SPOT_NAME": "Plaza",
    "EVENT_NAME": "Night Market",
    "MENU_ITEM_NAME": "Taco",
    "SKU": "SKU-1",
    "STAFF_NAME": "Worker",
}


def create_commissary_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["COMMISSARY_NAME"], "state_code": DEFAULTS["STATE_CODE"]}
    defaults.update(overrides)
    return defaults


def create_truck_payload(commissary_id: str, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TRUCK_NAME"],
        "commissary_id": commissary_id,
        "home_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def issue_health_permit_payload(truck_id: str, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "state_code": DEFAULTS["STATE_CODE"],
        "issued_at": DEFAULTS["ISSUED_AT"],
        "expires_at": DEFAULTS["EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_spot_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SPOT_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "concurrent_capacity": 2,
        "reservation_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["EVENT_NAME"],
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(truck_id: str, spot_id: str, event_id: str,
                           window_start: str, window_end: str,
                           expected_truck_version: int, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "spot_id": spot_id,
        "event_id": event_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_truck_version": expected_truck_version,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(truck_id: str, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["MENU_ITEM_NAME"],
        "unit_price_cents": 300,
        "par_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_prep_batch_payload(truck_id: str, menu_item_id: str, units_made: int = 10,
                              **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "menu_item_id": menu_item_id,
        "units_made": units_made,
    }
    defaults.update(overrides)
    return defaults


def create_staff_shift_payload(truck_id: str, role: str, shift_start: str, shift_end: str,
                               staff_name: str = None, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "staff_name": staff_name or DEFAULTS["STAFF_NAME"],
        "role": role,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    defaults.update(overrides)
    return defaults


def create_utility_log_payload(truck_id: str, utility: str, **overrides) -> dict:
    """PROPANE entries carry propane_psi_after; GENERATOR entries carry generator_delta_hours.
    The caller supplies the relevant field via **overrides."""
    defaults = {"truck_id": truck_id, "utility": utility}
    defaults.update(overrides)
    return defaults


def create_order_payload(booking_id: str, **overrides) -> dict:
    defaults = {"booking_id": booking_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id: str, menu_item_id: str, quantity: int,
                              **overrides) -> dict:
    defaults = {"order_id": order_id, "menu_item_id": menu_item_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def capture_payment_payload(**overrides) -> dict:
    """Optional tip_cents at capture; omitted by default (defaults to 0 server-side)."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def settle_payload(discount_code: str = "NONE", **overrides) -> dict:
    defaults = {"discount_code": discount_code}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
