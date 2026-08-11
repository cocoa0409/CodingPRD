"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import (
    BIN_CAPACITY_KG,
    PLAN_COM_DEFAULTS,
    PLAN_RES_DEFAULTS,
)


def create_service_plan_payload(**overrides) -> dict:
    """Residential plan defaults (weekly 1200, credit rate 10, allowance 2)."""
    defaults = dict(PLAN_RES_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_commercial_plan_payload(**overrides) -> dict:
    """Commercial plan defaults (base 3000, per-kg 7, included 40 kg)."""
    defaults = dict(PLAN_COM_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {"code": "R1", "weekday": "MON", "max_stops": 5}
    defaults.update(overrides)
    return defaults


def create_bin_payload(**overrides) -> dict:
    defaults = {"bin_type": "BIN_35L", "nominal_capacity_kg": BIN_CAPACITY_KG["BIN_35L"]}
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(**overrides) -> dict:
    defaults = {
        "email": "a@x.com",
        "full_name": "Sub A",
        "subscriber_type": "RESIDENTIAL",
        "address": "1 A St",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(
    subscriber_id, plan_id, route_id, start_date="2026-05-01", **overrides
) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "route_id": route_id,
        "start_date": start_date,
    }
    defaults.update(overrides)
    return defaults


def create_contamination_tag_payload(**overrides) -> dict:
    defaults = {"severity": "LOW", "category": "PLASTIC"}
    defaults.update(overrides)
    return defaults


def create_weigh_ticket_payload(service_date, gross_kg, tare_kg, **overrides) -> dict:
    defaults = {"service_date": service_date, "gross_kg": gross_kg, "tare_kg": tare_kg}
    defaults.update(overrides)
    return defaults


def create_redemption_payload(subscriber_id, bags, **overrides) -> dict:
    defaults = {"subscriber_id": subscriber_id, "bags": bags}
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(amount_cents, reason="promo", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_pause_payload(pause_start, pause_end, **overrides) -> dict:
    defaults = {"pause_start": pause_start, "pause_end": pause_end}
    defaults.update(overrides)
    return defaults
