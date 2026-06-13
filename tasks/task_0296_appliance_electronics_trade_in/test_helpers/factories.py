"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_PRICE_LOCK_HOURS,
    DEFAULT_REQUOTE_TOLERANCE_PCT,
    DEFAULT_RECYCLE_FLOOR_CENTS,
    BASE_VALUE_CENTS,
    CONDITION_MULTIPLIERS,
    DEFECT_DEDUCTIONS,
)

_EMAIL_SEQ = {"n": 0}


def _next_email() -> str:
    _EMAIL_SEQ["n"] += 1
    return f"cust{_EMAIL_SEQ['n']}@example.com"


def create_catalog_payload(**overrides) -> dict:
    """Catalog inputs (PRD §3.1). name + optional policy knobs; data_wipe_required_categories supplied explicitly."""
    defaults = {
        "name": "Trade-In Program",
        "currency": "USD",
        "price_lock_hours": DEFAULT_PRICE_LOCK_HOURS,
        "requote_tolerance_pct": DEFAULT_REQUOTE_TOLERANCE_PCT,
        "data_wipe_required_categories": [],
        "recycle_floor_value_cents": DEFAULT_RECYCLE_FLOOR_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_device_model_payload(**overrides) -> dict:
    """DeviceModel inputs (PRD §3.1)."""
    defaults = {
        "manufacturer": "Acme",
        "model_code": "PHN-1",
        "category": "SMARTPHONE",
        "base_value_cents": BASE_VALUE_CENTS,
        "condition_multipliers": dict(CONDITION_MULTIPLIERS),
        "defect_deductions": dict(DEFECT_DEDUCTIONS),
    }
    defaults.update(overrides)
    return defaults


def create_promotion_campaign_payload(**overrides) -> dict:
    """PromotionCampaign inputs (PRD §3.2)."""
    defaults = {
        "code": "SAVE10",
        "category_scope": "ALL",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "bonus_pct": 0.10,
        "bonus_flat_cents": 0,
        "bonus_cap_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Customer inputs (PRD §3.3)."""
    defaults = {
        "email": _next_email(),
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(customer_id: str, device_model_id: str, **overrides) -> dict:
    """TradeIn inputs (PRD §3.3). declared_defects / declared_powers_on / promo_code are optional."""
    defaults = {
        "customer_id": customer_id,
        "device_model_id": device_model_id,
        "declared_grade": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def inspect_payload(verified_grade: str, verified_powers_on: bool = True, **overrides) -> dict:
    """Inspection inputs (PRD §3.6). verified_defects optional (defaults empty)."""
    defaults = {
        "verified_grade": verified_grade,
        "verified_powers_on": verified_powers_on,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_slot_payload(lane_category: str, slot_start: str, slot_end: str, **overrides) -> dict:
    """InspectionSlot inputs (PRD §3.8)."""
    defaults = {
        "lane_category": lane_category,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    defaults.update(overrides)
    return defaults


def data_wipe_payload(method: str = "NIST_PURGE", result: str = "PASS", **overrides) -> dict:
    """DataWipeCertificate inputs (PRD §3.7)."""
    defaults = {"method": method, "result": result}
    defaults.update(overrides)
    return defaults


def payout_payload(method: str = "ACH", **overrides) -> dict:
    """Payout inputs (PRD §3.7). The operator supplies only the method."""
    defaults = {"method": method}
    defaults.update(overrides)
    return defaults
