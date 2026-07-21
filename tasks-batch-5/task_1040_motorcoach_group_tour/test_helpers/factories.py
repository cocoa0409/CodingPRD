"""Payload factories — one per entity, input fields only."""

DEFAULT_ITINERARY = [
    {
        "day_index": 1,
        "service_date": "2026-08-01",
        "from_city": "NYC",
        "to_city": "DC",
        "planned_drive_hours": 6,
    }
]


def create_tour_product_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Tour",
        "duration_days": 3,
        "base_price_per_person_cents": 100000,
        "deposit_per_person_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    defaults = {"code": "C1", "seat_capacity": 10, "day_rate_cents": 50000}
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {"name": "Test Driver", "license_no": "CDL1", "day_rate_cents": 40000}
    defaults.update(overrides)
    return defaults


def create_guide_payload(**overrides) -> dict:
    defaults = {"name": "Test Guide", "day_rate_cents": 30000}
    defaults.update(overrides)
    return defaults


def create_departure_payload(tour_product_id, **overrides) -> dict:
    defaults = {
        "tour_product_id": tour_product_id,
        "name": "Test Departure",
        "start_date": "2026-08-01",
        "end_date": "2026-08-03",
        "guaranteed_min_pax": 5,
        "itinerary_days": [dict(d) for d in DEFAULT_ITINERARY],
    }
    defaults.update(overrides)
    return defaults


def create_hotel_block_payload(departure_id, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "hotel_name": "Test Hotel",
        "city": "DC",
        "room_count": 10,
        "nights": 2,
        "rate_per_room_night_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(departure_id, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "lead_name": "Test Party",
        "pax_count": 2,
        "rooms_requested": 0,
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(booking_id, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "full_name": "Test Passenger"}
    defaults.update(overrides)
    return defaults


def create_payment_payload(booking_id, kind, amount_cents, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def itinerary(drive_hours, service_date="2026-08-01", day_index=1,
              from_city="NYC", to_city="DC") -> list:
    """Single-day itinerary with a given planned_drive_hours (drives the DOT check)."""
    return [{
        "day_index": day_index,
        "service_date": service_date,
        "from_city": from_city,
        "to_city": to_city,
        "planned_drive_hours": drive_hours,
    }]
