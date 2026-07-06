"""Payload factories — one per entity, input fields only.

Default dates are chosen relative to the logical clock startup default
(2026-03-01T00:00:00Z): depart/return well in the future so reserve passes age
checks and refund lead-time arithmetic is predictable.
"""

DEFAULTS = {
    "BASE_PRICE": 9000,
    "GRATUITY_PCT": 0.18,
    "DEPART_AT": "2026-04-10T18:00:00Z",
    "RETURN_AT": "2026-04-10T23:00:00Z",
    "SEAT_CAPACITY": 12,
    "ADULT_BIRTH_DATE": "1990-01-01T00:00:00Z",
}


def create_tour_product_payload(**overrides) -> dict:
    payload = {
        "name": "Napa Cellar Crawl",
        "theme": "WINE",
        "base_price_per_person_cents": DEFAULTS["BASE_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_add_on_payload(tour_product_id, **overrides) -> dict:
    payload = {
        "tour_product_id": tour_product_id,
        "name": "Cheese Pairing Flight",
        "price_per_person_cents": 1500,
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides) -> dict:
    payload = {"label": "Van-1", "seat_capacity": DEFAULTS["SEAT_CAPACITY"]}
    payload.update(overrides)
    return payload


def create_partner_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Oak Ridge Cellars",
        "kind": "WINERY",
        "commission_pct": 0.10,
        "tasting_cost_per_guest_cents": 1200,
    }
    payload.update(overrides)
    return payload


def create_pickup_point_payload(**overrides) -> dict:
    payload = {"name": "Downtown Transit Hub", "address": "1 Main St"}
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {"full_name": "Ada Guest", "birth_date": DEFAULTS["ADULT_BIRTH_DATE"]}
    payload.update(overrides)
    return payload


def create_departure_payload(tour_product_id, vehicle_id, **overrides) -> dict:
    payload = {
        "tour_product_id": tour_product_id,
        "vehicle_id": vehicle_id,
        "depart_at": DEFAULTS["DEPART_AT"],
        "return_at": DEFAULTS["RETURN_AT"],
    }
    payload.update(overrides)
    return payload


def create_stop_payload(departure_id, partner_venue_id, **overrides) -> dict:
    payload = {
        "departure_id": departure_id,
        "partner_venue_id": partner_venue_id,
        "sequence": 1,
        "dwell_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_venue_confirmation_payload(stop_id, **overrides) -> dict:
    payload = {"stop_id": stop_id, "requested_headcount": 6}
    payload.update(overrides)
    return payload


def create_booking_payload(departure_id, lead_guest_id, pickup_point_id, party_size,
                           add_on_id=None, **overrides) -> dict:
    payload = {
        "departure_id": departure_id,
        "lead_guest_id": lead_guest_id,
        "pickup_point_id": pickup_point_id,
        "party_size": party_size,
    }
    if add_on_id is not None:
        payload["add_on_id"] = add_on_id
    payload.update(overrides)
    return payload
