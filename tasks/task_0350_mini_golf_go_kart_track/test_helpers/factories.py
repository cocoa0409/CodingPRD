"""Payload factories — one per creatable resource, input fields only.

Each factory returns a fresh dict and applies **overrides last, so a test may
add, replace, or (by passing None) clear any field.
"""

DEFAULTS = {
    "VENUE_NAME": "Test Track",
    "ATTRACTION_NAME": "Test Attraction",
    "PLAN_NAME": "Test Plan",
    "PACKAGE_NAME": "Test Party",
    "GUEST_NAME": "Test Guest",
    "BASE_PRICE_CENTS": 1000,
}


def create_venue_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["VENUE_NAME"]}
    payload.update(overrides)
    return payload


def create_attraction_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "name": DEFAULTS["ATTRACTION_NAME"],
        "kind": "GO_KART",
    }
    payload.update(overrides)
    return payload


def create_pricing_plan_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "name": DEFAULTS["PLAN_NAME"],
        "mode": "PER_HEAT",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_heat_payload(venue_id, attraction_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "attraction_id": attraction_id,
        "start_utc": "2026-06-14T10:00:00Z",
        "end_utc": "2026-06-14T10:15:00Z",
    }
    payload.update(overrides)
    return payload


def create_tee_session_payload(venue_id, attraction_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "attraction_id": attraction_id,
        "start_utc": "2026-06-14T10:00:00Z",
        "end_utc": "2026-06-14T11:00:00Z",
        "party_slot_capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["GUEST_NAME"],
        "height_cm": 175,
    }
    payload.update(overrides)
    return payload


def create_waiver_payload(guest_id, **overrides) -> dict:
    payload = {"guest_id": guest_id}
    payload.update(overrides)
    return payload


def create_combo_pass_payload(guest_id, total_credits, **overrides) -> dict:
    payload = {"guest_id": guest_id, "total_credits": total_credits}
    payload.update(overrides)
    return payload


def create_party_group_payload(venue_id, host_guest_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "host_guest_id": host_guest_id,
        "package_name": DEFAULTS["PACKAGE_NAME"],
        "included_unit_count": 10,
        "deposit_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(venue_id, guest_id, pricing_plan_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "guest_id": guest_id,
        "slot_kind": "HEAT",
        "pricing_plan_id": pricing_plan_id,
        "origin": "RESERVATION",
        "party_size": 1,
    }
    payload.update(overrides)
    return payload


def top_up_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def redemption_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
