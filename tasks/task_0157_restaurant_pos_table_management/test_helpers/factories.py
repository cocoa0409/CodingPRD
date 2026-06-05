"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides for the fields a
test needs to control. Only fields the PRD declares as client input appear here;
computed and system fields (status, subtotals, current_utc, etc.) are never sent.
"""


def create_restaurant_payload(**overrides) -> dict:
    """POST /restaurants. Required: name, tax_rate_bps. Optional (with PRD
    defaults): large_party_threshold(8), auto_gratuity_bps(2000),
    comp_cap_bps(10000), min_rest_minutes(0)."""
    defaults = {"name": "Test Bistro", "tax_rate_bps": 0}
    defaults.update(overrides)
    return defaults


def set_clock_payload(restaurant_id: str, to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc."""
    return {"restaurant_id": restaurant_id, "to_iso8601": to_iso8601}


def create_menu_item_payload(restaurant_id: str, **overrides) -> dict:
    """POST /menu-items. All fields required: name, station, base_price_cents,
    happy_hour_price_cents, initial_available_count."""
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "Test Item",
        "station": "GRILL",
        "base_price_cents": 1000,
        "happy_hour_price_cents": 1000,
        "initial_available_count": 50,
    }
    defaults.update(overrides)
    return defaults


def create_happy_hour_window_payload(restaurant_id: str, **overrides) -> dict:
    """POST /happy-hour-windows. Required: day_of_week, start_minute, end_minute."""
    defaults = {
        "restaurant_id": restaurant_id,
        "day_of_week": 1,
        "start_minute": 1020,
        "end_minute": 1080,
    }
    defaults.update(overrides)
    return defaults


def create_table_payload(restaurant_id: str, **overrides) -> dict:
    """POST /tables. Required: table_number, capacity."""
    defaults = {
        "restaurant_id": restaurant_id,
        "table_number": "T1",
        "capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def buss_table_payload(expected_table_version: int) -> dict:
    """POST /tables/{id}/buss. Required: expected_table_version (non-optional)."""
    return {"expected_table_version": expected_table_version}


def create_waitlist_payload(restaurant_id: str, **overrides) -> dict:
    """POST /waitlist. Required: party_name, party_size."""
    defaults = {
        "restaurant_id": restaurant_id,
        "party_name": "Test Party",
        "party_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_seating_payload(restaurant_id: str, table_id: str, **overrides) -> dict:
    """POST /seatings. Required: table_id, party_size. Optional: waitlist_entry_id."""
    defaults = {
        "restaurant_id": restaurant_id,
        "table_id": table_id,
        "party_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(restaurant_id: str, **overrides) -> dict:
    """POST /staff-members. Required: name, role, tip_weight_bps."""
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "Sam",
        "role": "SERVER",
        "tip_weight_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_staff_shift_payload(restaurant_id: str, staff_id: str, **overrides) -> dict:
    """POST /staff-shifts. Required: staff_id, business_date, clock_in_minute,
    clock_out_minute."""
    defaults = {
        "restaurant_id": restaurant_id,
        "staff_id": staff_id,
        "business_date": "2026-06-01",
        "clock_in_minute": 600,
        "clock_out_minute": 1080,
    }
    defaults.update(overrides)
    return defaults


def create_check_payload(restaurant_id: str, seating_id: str, server_staff_id: str, **overrides) -> dict:
    """POST /checks. Required: seating_id, server_staff_id, party_size."""
    defaults = {
        "restaurant_id": restaurant_id,
        "seating_id": seating_id,
        "server_staff_id": server_staff_id,
        "party_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(restaurant_id: str, check_id: str, **overrides) -> dict:
    """POST /courses. Required: check_id, course_number."""
    defaults = {
        "restaurant_id": restaurant_id,
        "check_id": check_id,
        "course_number": 1,
    }
    defaults.update(overrides)
    return defaults


def create_order_item_payload(restaurant_id: str, course_id: str, menu_item_id: str, **overrides) -> dict:
    """POST /order-items. Required: course_id, menu_item_id, quantity."""
    defaults = {
        "restaurant_id": restaurant_id,
        "course_id": course_id,
        "menu_item_id": menu_item_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_item_modifier_payload(restaurant_id: str, order_item_id: str, **overrides) -> dict:
    """POST /item-modifiers. Required: order_item_id, name, surcharge_cents."""
    defaults = {
        "restaurant_id": restaurant_id,
        "order_item_id": order_item_id,
        "name": "extra cheese",
        "surcharge_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(restaurant_id: str, check_id: str, **overrides) -> dict:
    """POST /payments. Required: check_id, amount_cents, tip_cents, method."""
    defaults = {
        "restaurant_id": restaurant_id,
        "check_id": check_id,
        "amount_cents": 0,
        "tip_cents": 0,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_tip_pool_payload(restaurant_id: str, business_date: str, **overrides) -> dict:
    """POST /tip-pools. Required: business_date. Optional: distribution_mode
    (defaults to EVEN_BY_HOURS)."""
    defaults = {
        "restaurant_id": restaurant_id,
        "business_date": business_date,
    }
    defaults.update(overrides)
    return defaults


def split_check_payload(n: int) -> dict:
    """POST /checks/{id}/split. Required: n."""
    return {"n": n}
