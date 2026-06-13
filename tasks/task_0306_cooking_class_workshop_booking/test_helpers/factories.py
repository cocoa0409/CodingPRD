"""Payload factories — one per entity, input fields only (PRD §3, §4).

Each factory returns a dict of the required input fields with sensible
defaults; pass **overrides to control specific values, or pop a key to test
a missing-required-field case.
"""

DEFAULTS = {
    "INSTRUCTOR_NAME": "Test Chef",
    "MEMBER_NAME": "Test Member",
    "TEMPLATE_TITLE": "Test Class",
    "BASE_PRICE_CENTS": 5000,
    "DEFAULT_CAPACITY": 4,
    "STATION_FIXED_COST_CENTS": 1000,
    "PREP_MINUTES": 0,
    "CLEANUP_MINUTES": 0,
}

_email_counter = [0]


def _unique_email(prefix="user"):
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "email": _unique_email("chef"),
        "max_skill_level": "PROFESSIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    # dietary_flags is optional (defaults to []) — not included by default.
    defaults = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": _unique_email("member"),
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["TEMPLATE_TITLE"],
        "skill_level": "BEGINNER",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "default_capacity": DEFAULTS["DEFAULT_CAPACITY"],
        "station_fixed_cost_cents": DEFAULTS["STATION_FIXED_COST_CENTS"],
        "prep_minutes": DEFAULTS["PREP_MINUTES"],
        "cleanup_minutes": DEFAULTS["CLEANUP_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(template_id, instructor_id, **overrides) -> dict:
    defaults = {
        "template_id": template_id,
        "instructor_id": instructor_id,
        "cadence": "WEEKLY",
        "occurrence_count": 1,
        "first_start_at": "2026-09-05T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(template_id, instructor_id, **overrides) -> dict:
    # private_event_fee_cents and series_id are optional inputs.
    defaults = {
        "template_id": template_id,
        "instructor_id": instructor_id,
        "station_id": "ST-DEFAULT",
        "event_type": "GROUP",
        "start_at": "2026-09-10T14:00:00Z",
        "end_at": "2026-09-10T16:00:00Z",
        "planned_seats": DEFAULTS["DEFAULT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_line_payload(**overrides) -> dict:
    # dietary_tag is optional (defaults to NEUTRAL).
    defaults = {
        "name": "ingredient",
        "qty_per_seat": 1,
        "unit_cost_cents": 1,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(session_id, member_id, seats_requested=1, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "member_id": member_id,
        "seats_requested": seats_requested,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_payload(member_id, seats_requested=1, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "seats_requested": seats_requested,
    }
    defaults.update(overrides)
    return defaults


def create_substitution_payload(booking_id, ingredient_line_id,
                                alternate_unit_cost_cents, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "ingredient_line_id": ingredient_line_id,
        "alternate_unit_cost_cents": alternate_unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


_gc_code_counter = [0]


def _unique_code(prefix="GC"):
    _gc_code_counter[0] += 1
    return f"{prefix}-{_gc_code_counter[0]}"


def create_gift_card_payload(owner_member_id, initial_value_cents=10000, **overrides) -> dict:
    defaults = {
        "code": _unique_code(),
        "owner_member_id": owner_member_id,
        "initial_value_cents": initial_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_wallet_adjustment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
