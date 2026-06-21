"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults for required fields and accepts
**overrides for any value a test needs to control. Optional fields are left out
of defaults unless a test supplies them.
"""

DEFAULTS = {
    "DISTRIBUTOR_NAME": "Acme Films",
    "FILM_TITLE": "F",
    "RUNTIME_MINUTES": 90,
    "RELEASE_DATE": "2026-06-01T00:00:00.000Z",
    "AUDITORIUM_NAME": "Hall 1",
    "SEAT_COUNT": 4,
    "TURNAROUND_MINUTES": 20,
    "BASE_PRICE_CENTS": 1000,
    "COMBO_NAME": "Combo",
    "COMBO_PRICE_CENTS": 1000,
    "MEMBER_EMAIL": "m@x.com",
    "MEMBER_NAME": "M",
}


def create_distributor_payload(**overrides) -> dict:
    """POST /distributors — required: name. Optional: minimum_guarantee_cents."""
    payload = {"name": DEFAULTS["DISTRIBUTOR_NAME"]}
    payload.update(overrides)
    return payload


def create_film_payload(distributor_id, **overrides) -> dict:
    """POST /films — required: title, runtime_minutes, distributor_id,
    release_date, split_schedule."""
    payload = {
        "title": DEFAULTS["FILM_TITLE"],
        "runtime_minutes": DEFAULTS["RUNTIME_MINUTES"],
        "distributor_id": distributor_id,
        "release_date": DEFAULTS["RELEASE_DATE"],
        "split_schedule": [{"week_index": 0, "distributor_pct": 0.70}],
    }
    payload.update(overrides)
    return payload


def create_auditorium_payload(**overrides) -> dict:
    """POST /auditoriums — required: name, seat_count. Optional: turnaround_minutes."""
    payload = {
        "name": DEFAULTS["AUDITORIUM_NAME"],
        "seat_count": DEFAULTS["SEAT_COUNT"],
        "turnaround_minutes": DEFAULTS["TURNAROUND_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_showtime_payload(film_id, starts_at, **overrides) -> dict:
    """POST /auditoriums/{id}/showtimes — required: film_id, starts_at,
    pricing_profile, base_price_cents. Optional: rental_basis, private_rental_fee_cents."""
    payload = {
        "film_id": film_id,
        "starts_at": starts_at,
        "pricing_profile": "STANDARD",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_combo_payload(**overrides) -> dict:
    """POST /combos — required: name, price_cents. Optional: member_discount_pct."""
    payload = {
        "name": DEFAULTS["COMBO_NAME"],
        "price_cents": DEFAULTS["COMBO_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    """POST /members — required: email, full_name."""
    payload = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_order_payload(member_id, seat_ids, expected_showtime_version, **overrides) -> dict:
    """POST /showtimes/{id}/orders — required: member_id, seat_ids,
    expected_showtime_version. Optional: combo_ids, apply_wallet_credit."""
    payload = {
        "member_id": member_id,
        "seat_ids": seat_ids,
        "expected_showtime_version": expected_showtime_version,
    }
    payload.update(overrides)
    return payload
