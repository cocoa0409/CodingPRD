"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import CANONICAL_SCHEDULE, CANONICAL_UNIT, TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "C1",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grain_lot_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "commodity": "CORN",
        "gross_weight_lbs": TEST_DEFAULTS["GROSS_WEIGHT_LBS"],
        "tare_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"],
        "target_moisture_pct": TEST_DEFAULTS["TARGET_MOISTURE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_moisture_test_payload(lot_id: str, expected_grain_lot_version, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "sample_moisture_pct": 20.0,
        "expected_grain_lot_version": expected_grain_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_schedule_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_SCHEDULE)
    defaults.update(overrides)
    return defaults


def create_dryer_unit_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_UNIT)
    defaults.update(overrides)
    return defaults


def create_queue_ticket_payload(lot_id: str, unit_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "unit_id": unit_id,
        "window_date": "2026-09-12",
        "requested_bushels": 200,
    }
    defaults.update(overrides)
    return defaults


def create_dryer_run_payload(unit_id: str, lot_id: str, queue_ticket_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "lot_id": lot_id,
        "queue_ticket_id": queue_ticket_id,
        "scheduled_start": TEST_DEFAULTS["RUN_START"],
        "scheduled_end": TEST_DEFAULTS["RUN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_blend_order_payload(high_moisture_lot_id: str, low_moisture_lot_id: str, **overrides) -> dict:
    defaults = {
        "high_moisture_lot_id": high_moisture_lot_id,
        "low_moisture_lot_id": low_moisture_lot_id,
        "target_moisture_pct": 15.5,
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(lot_id: str, dryer_run_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "dryer_run_id": dryer_run_id,
        "damage_type": "HEAT_DAMAGE",
        "claimed_amount_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_storage_agreement_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "daily_rate_cents_per_bu": 0.15,
        "min_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, expected_invoice_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults
