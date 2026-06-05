"""Payload factories — one per entity, input fields only."""
from .constants import (
    STANDARD_BASE_PRICE_CENTS,
    STANDARD_DEEP_CLEAN_PCT,
    STANDARD_MOVE_OUT_PCT,
    STANDARD_SUPPLIES_FEE_CENTS,
    TEST_POSTAL_CODE,
)

_email_counter = [0]


def _unique_email(prefix: str) -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@x.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": _unique_email("cust"), "full_name": "Cust"}
    defaults.update(overrides)
    return defaults


def create_address_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "line1": "1 A St",
        "postal_code": TEST_POSTAL_CODE,
        "home_size": "STUDIO",
    }
    defaults.update(overrides)
    return defaults


def create_cleaner_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email("cl"),
        "full_name": "C One",
        "service_postal_codes": [TEST_POSTAL_CODE],
    }
    defaults.update(overrides)
    return defaults


def create_pricing_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "2026 Standard",
        "base_price_cents": dict(STANDARD_BASE_PRICE_CENTS),
        "deep_clean_surcharge_pct": STANDARD_DEEP_CLEAN_PCT,
        "move_out_surcharge_pct": STANDARD_MOVE_OUT_PCT,
        "supplies_fee_cents": STANDARD_SUPPLIES_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_preferred_pro_payload(customer_id: str, cleaner_id: str, priority: int = 1, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "cleaner_id": cleaner_id, "priority": priority}
    defaults.update(overrides)
    return defaults


def create_booking_series_payload(customer_id: str, address_id: str, pricing_plan_id: str,
                                  first_occurrence_date: str, cadence: str = "WEEKLY", **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address_id": address_id,
        "pricing_plan_id": pricing_plan_id,
        "cadence": cadence,
        "first_occurrence_date": first_occurrence_date,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(customer_id: str, address_id: str, pricing_plan_id: str,
                           scheduled_start: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address_id": address_id,
        "pricing_plan_id": pricing_plan_id,
        "scheduled_start": scheduled_start,
    }
    defaults.update(overrides)
    return defaults


def create_tip_payload(booking_id: str, customer_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "customer_id": customer_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
