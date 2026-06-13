"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the request body. Required fields get sensible
defaults; **overrides lets a test control whatever it needs. FK ids that have no
universal default are explicit positional/keyword parameters.
"""

DEFAULTS = {
    "CUSTOMER_EMAIL": "customer@example.com",
    "CUSTOMER_NAME": "Test Customer",
    "VEHICLE_PLATE": "TESTPLATE",
    "LOT_NAME": "Test Lot",
    "DAILY_CAP_CENTS": 2000,
    "HOURLY_CENTS": 300,
    "SCHEDULED_START": "2026-07-01T10:00:00Z",
    "SCHEDULED_END": "2026-07-02T10:00:00Z",
    "DEPART_AT": "2026-07-01T12:00:00Z",
    "SEAT_CAPACITY": 4,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "full_name": DEFAULTS["CUSTOMER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plate": DEFAULTS["VEHICLE_PLATE"],
        "size_class": "STANDARD",
        "is_ev": False,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LOT_NAME"],
        "kind": "SURFACE_LOT",
        "standard_capacity": 5,
        "oversized_capacity": 0,
        "ev_capacity": 0,
        "in_out_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "rate_mode": "DAILY",
        "daily_cap_cents": DEFAULTS["DAILY_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_policy_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "free_cancel_hours": 48,
    }
    defaults.update(overrides)
    return defaults


def create_shuttle_trip_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "depart_at": DEFAULTS["DEPART_AT"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id: str, lot_id: str, vehicle_id: str,
                               rate_plan_id: str, expected_lot_version: int,
                               **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "lot_id": lot_id,
        "vehicle_id": vehicle_id,
        "rate_plan_id": rate_plan_id,
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
        "prepaid": False,
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def assign_shuttle_payload(shuttle_trip_id: str, expected_shuttle_trip_version: int,
                           **overrides) -> dict:
    defaults = {
        "shuttle_trip_id": shuttle_trip_id,
        "expected_shuttle_trip_version": expected_shuttle_trip_version,
    }
    defaults.update(overrides)
    return defaults


def clock_set_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def clock_advance_payload(minutes: int) -> dict:
    return {"minutes": minutes}
