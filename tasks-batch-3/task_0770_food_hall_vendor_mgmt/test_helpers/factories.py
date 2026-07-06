"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_food_hall_payload(**overrides) -> dict:
    defaults = {
        "name": "Central Hall",
        "total_seating_capacity": 100,
        "common_area_capacity": 500,
        "hall_open_minutes": 480,
        "hall_close_minutes": 1320,
        "event_buffer_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Vendor",
        "contact_email": "vendor@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_stall_payload(food_hall_id: str, **overrides) -> dict:
    defaults = {
        "food_hall_id": food_hall_id,
        "stall_code": "A-1",
        "size_sqft": 200,
        "open_minutes": 480,
        "close_minutes": 1320,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(stall_id: str, vendor_id: str, **overrides) -> dict:
    defaults = {
        "stall_id": stall_id,
        "vendor_id": vendor_id,
        "start_date": "2026-06-01",
        "end_date": "2026-12-31",
        "base_rent_cents": 200000,
        "percentage_rate": 0.08,
        "natural_breakpoint_cents": 5000000,
        "rent_cap_cents": 100000000,
        "security_deposit_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(stall_id: str, **overrides) -> dict:
    defaults = {
        "stall_id": stall_id,
        "permit_number": "P-1",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(stall_id: str, **overrides) -> dict:
    defaults = {
        "stall_id": stall_id,
        "scheduled_for": "2026-06-15T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(food_hall_id: str, stall_id: str, **overrides) -> dict:
    defaults = {
        "food_hall_id": food_hall_id,
        "stall_id": stall_id,
        "gross_amount_cents": 1500,
        "item_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_seating_allocation_payload(food_hall_id: str, **overrides) -> dict:
    defaults = {
        "food_hall_id": food_hall_id,
        "seats": 4,
        "start_time": "2026-06-15T10:00:00Z",
        "end_time": "2026-06-15T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_marketing_event_payload(food_hall_id: str, **overrides) -> dict:
    defaults = {
        "food_hall_id": food_hall_id,
        "name": "Event",
        "start_time": "2026-07-01T09:00:00Z",
        "end_time": "2026-07-01T12:00:00Z",
        "reserved_capacity": 100,
        "expected_footfall": 200,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(lease_id: str, expected_lease_version: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults
