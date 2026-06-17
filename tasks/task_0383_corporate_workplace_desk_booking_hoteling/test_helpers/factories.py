"""Payload factories — one per entity, input fields only (PRD-exact names)."""


def create_site_payload(**overrides) -> dict:
    """Required: name. Optional: timezone (default "UTC")."""
    payload = {"name": "Test HQ"}
    payload.update(overrides)
    return payload


def create_floor_payload(**overrides) -> dict:
    """Required: level. Optional: workday_start_minute (default 540),
    workday_end_minute (default 1080)."""
    payload = {"level": 1}
    payload.update(overrides)
    return payload


def create_capacity_policy_payload(**overrides) -> dict:
    """All inputs optional: max_active_reservations_per_employee (default 1),
    grace_minutes (default 30), enforce_team_zoning (default true)."""
    payload = {}
    payload.update(overrides)
    return payload


def create_neighborhood_payload(**overrides) -> dict:
    """Required: name. Optional: team_code (default null),
    capacity_cap_pct (default 100)."""
    payload = {"name": "Test Zone"}
    payload.update(overrides)
    return payload


def create_seat_payload(**overrides) -> dict:
    """Required: label. Optional: is_standing (default false)."""
    payload = {"label": "S1"}
    payload.update(overrides)
    return payload


def create_room_payload(**overrides) -> dict:
    """Required: label, seats_capacity. Optional: turnover_buffer_minute (default 15)."""
    payload = {"label": "R1", "seats_capacity": 6}
    payload.update(overrides)
    return payload


def create_employee_payload(**overrides) -> dict:
    """Required: email, full_name, team_code."""
    payload = {"email": "test@x.com", "full_name": "Test Employee", "team_code": "ENG"}
    payload.update(overrides)
    return payload


def create_reservation_payload(**overrides) -> dict:
    """Required: employee_id, resource_type, booking_date, start_minute, end_minute.
    Conditionally required: seat_id (SEAT) or room_id (ROOM).
    Optional: expected_seat_version / expected_room_version (OCC guard)."""
    payload = {
        "resource_type": "SEAT",
        "booking_date": "2026-06-20",
        "start_minute": 540,
        "end_minute": 600,
    }
    payload.update(overrides)
    return payload


def create_amenity_payload(**overrides) -> dict:
    """Required: amenity_code, unit_price_cents, quantity."""
    payload = {"amenity_code": "MONITOR", "unit_price_cents": 1000, "quantity": 1}
    payload.update(overrides)
    return payload


def create_visitor_pass_payload(**overrides) -> dict:
    """Required: host_employee_id, seat_id, visitor_name, booking_date,
    start_minute, end_minute."""
    payload = {
        "visitor_name": "Test Guest",
        "booking_date": "2026-06-24",
        "start_minute": 600,
        "end_minute": 720,
    }
    payload.update(overrides)
    return payload
