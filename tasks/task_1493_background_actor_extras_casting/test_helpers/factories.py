"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n():
    return next(_counter)


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": f"{TEST_DEFAULTS['TITLE']} {_n()}",
        "studio_code": TEST_DEFAULTS["STUDIO_CODE"],
        "payroll_company_name": TEST_DEFAULTS["PAYROLL_COMPANY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_actor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Performer {_n()}",
        "union_status": "NONUNION",
    }
    defaults.update(overrides)
    return defaults


def create_casting_call_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "shoot_date": TEST_DEFAULTS["SHOOT_DATE"],
        "general_call_time": TEST_DEFAULTS["GENERAL_CALL_TIME"],
        "scheduled_duration_minutes": TEST_DEFAULTS["SCHEDULED_DURATION_MINUTES"],
        "location": f"{TEST_DEFAULTS['LOCATION']}-{_n()}",
        "union_slots": 0,
        "nonunion_slots": 1,
        "union_rate_cents": TEST_DEFAULTS["UNION_RATE_CENTS"],
        "nonunion_rate_cents": TEST_DEFAULTS["NONUNION_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_look_requirement_payload(casting_call_id, **overrides) -> dict:
    defaults = {
        "casting_call_id": casting_call_id,
        "category": "WARDROBE_OWN",
        "description": "1920s tuxedo, actor-provided",
        "bump_amount_cents": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_holding_area_payload(casting_call_id, **overrides) -> dict:
    defaults = {
        "casting_call_id": casting_call_id,
        "name": f"Basecamp {_n()}",
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(casting_call_id, actor_id, **overrides) -> dict:
    defaults = {
        "casting_call_id": casting_call_id,
        "actor_id": actor_id,
    }
    defaults.update(overrides)
    return defaults


def create_time_event_payload(booking_id, event_type, occurred_at, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_bump_payload(voucher_id, **overrides) -> dict:
    defaults = {
        "voucher_id": voucher_id,
        "category": "WARDROBE_OWN",
        "amount_cents": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_batch_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "period_label": TEST_DEFAULTS["PERIOD_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_standby_entry_payload(casting_call_id, actor_id) -> dict:
    return {"casting_call_id": casting_call_id, "actor_id": actor_id}


def create_ratio_waiver_payload(casting_call_id, **overrides) -> dict:
    defaults = {
        "casting_call_id": casting_call_id,
        "union_slot_reduction": 1,
        "justification": "regional union pool shortage",
    }
    defaults.update(overrides)
    return defaults
