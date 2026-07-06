"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VENUE_NAME": "Fright Park",
    "TIMEZONE": "UTC",
    "ATTRACTION_NAME": "Crypt",
    "GA_BASE_PRICE_CENTS": 2410,
    "WINDOW_START": "2026-10-31T18:00:00Z",
    "WINDOW_END": "2026-10-31T19:00:00Z",
    "GUEST_EMAIL": "guest@x.com",
}


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "timezone": DEFAULTS["TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def weather_payload(weather_status, expected_venue_version, **overrides) -> dict:
    defaults = {
        "weather_status": weather_status,
        "expected_venue_version": expected_venue_version,
    }
    defaults.update(overrides)
    return defaults


def create_attraction_payload(venue_id, **overrides) -> dict:
    # requires_waiver is optional (PRD: defaults to true when omitted); included
    # explicitly here so most setups don't need a waiver. Tests that exercise the
    # default omit it via overrides.
    defaults = {
        "venue_id": venue_id,
        "name": DEFAULTS["ATTRACTION_NAME"],
        "min_age": 0,
        "scare_level": 1,
        "throughput_per_slot": 10,
        "requires_waiver": False,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_rule_payload(tier="GA", **overrides) -> dict:
    # Band params are all optional in the PRD; supplied only when a test pins them.
    defaults = {
        "tier": tier,
        "base_price_cents": DEFAULTS["GA_BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_time_slot_payload(**overrides) -> dict:
    defaults = {
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Guest",
        "age": 30,
        "email": DEFAULTS["GUEST_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(max_scare_level=5, **overrides) -> dict:
    defaults = {"max_scare_level": max_scare_level}
    defaults.update(overrides)
    return defaults


def create_pass_product_payload(kind="SEASON", **overrides) -> dict:
    # min_party is optional (defaults to 1); supplied only when a test pins it.
    defaults = {
        "kind": kind,
        "price_cents": 5000,
        "discount_pct": 10,
        "max_redemptions": 5,
    }
    defaults.update(overrides)
    return defaults


def create_pass_payload(pass_product_id, guest_id, **overrides) -> dict:
    defaults = {
        "pass_product_id": pass_product_id,
        "guest_id": guest_id,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(venue_id, guest_id, **overrides) -> dict:
    # pass_id is optional; supplied only when a test applies a pass.
    defaults = {
        "venue_id": venue_id,
        "guest_id": guest_id,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(time_slot_id, guest_age=30, max_scare_level=1,
                          tier="GA", **overrides) -> dict:
    defaults = {
        "time_slot_id": time_slot_id,
        "guest_age": guest_age,
        "max_scare_level": max_scare_level,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def confirm_payload(expected_time_slot_version, **overrides) -> dict:
    defaults = {"expected_time_slot_version": expected_time_slot_version}
    defaults.update(overrides)
    return defaults


def create_scare_zone_payload(name="Crypt Zone", min_actors=1, **overrides) -> dict:
    defaults = {"name": name, "min_actors": min_actors}
    defaults.update(overrides)
    return defaults


def create_actor_shift_payload(actor_user_id, shift_start, shift_end, **overrides) -> dict:
    defaults = {
        "actor_user_id": actor_user_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(reason, expected_attraction_version, **overrides) -> dict:
    defaults = {
        "reason": reason,
        "expected_attraction_version": expected_attraction_version,
    }
    defaults.update(overrides)
    return defaults


def revoke_payload(expected_waiver_version, **overrides) -> dict:
    defaults = {"expected_waiver_version": expected_waiver_version}
    defaults.update(overrides)
    return defaults


def close_for_season_payload(expected_attraction_version, **overrides) -> dict:
    defaults = {"expected_attraction_version": expected_attraction_version}
    defaults.update(overrides)
    return defaults


def lift_payload(expected_attraction_version, **overrides) -> dict:
    defaults = {"expected_attraction_version": expected_attraction_version}
    defaults.update(overrides)
    return defaults
