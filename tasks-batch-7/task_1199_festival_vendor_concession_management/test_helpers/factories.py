"""Payload factories — one per entity, input fields only."""
from .constants import EVENT_END_ISO, EVENT_START_ISO, IN_WINDOW_SALE_ISO, TEST_DEFAULTS


def create_festival_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Fest",
        "event_start": EVENT_START_ISO,
        "event_end": EVENT_END_ISO,
        "category_cap_per_category": TEST_DEFAULTS["CATEGORY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Vendor LLC",
        "contact_email": "ops@testvendor.com",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(vendor_id, festival_id, **overrides) -> dict:
    """Submit payload. Proposed terms are included per fee_model unless overridden."""
    fee_model = overrides.get("fee_model", "FLAT_FEE")
    defaults = {
        "vendor_id": vendor_id,
        "festival_id": festival_id,
        "category": "FOOD_HOT",
        "fee_model": fee_model,
        "power_needed_amps": TEST_DEFAULTS["POWER_DRAW_AMPS"],
        "requires_water": False,
    }
    if fee_model in ("FLAT_FEE", "HYBRID"):
        defaults["proposed_flat_fee_cents"] = TEST_DEFAULTS["FLAT_FEE_CENTS"]
    if fee_model in ("REVENUE_SHARE", "HYBRID"):
        defaults["proposed_revenue_share_pct_bp"] = TEST_DEFAULTS["REVENUE_SHARE_PCT_BP"]
    defaults.update(overrides)
    return defaults


def curated_terms_payload(fee_model="FLAT_FEE", flat_fee_cents=50000,
                          revenue_share_pct_bp=1000, tier_mode="MARGINAL",
                          minimum_guarantee_cents=100000, free_allowance_cents=150000) -> dict:
    """Complete curated term set for an ACCEPT decision, per fee model."""
    terms = {"curated_fee_model": fee_model}
    if fee_model in ("FLAT_FEE", "HYBRID"):
        terms["curated_flat_fee_cents"] = flat_fee_cents
    if fee_model in ("REVENUE_SHARE", "HYBRID"):
        terms["curated_revenue_share_pct_bp"] = revenue_share_pct_bp
    if fee_model == "REVENUE_SHARE":
        terms["curated_tier_mode"] = tier_mode
    if fee_model == "HYBRID":
        terms["curated_minimum_guarantee_cents"] = minimum_guarantee_cents
        terms["curated_free_allowance_cents"] = free_allowance_cents
    return terms


def decide_payload(decision="ACCEPTED", **curated) -> dict:
    payload = {"decision": decision}
    payload.update(curated)
    return payload


def create_zone_payload(festival_id, **overrides) -> dict:
    defaults = {
        "festival_id": festival_id,
        "name": "North",
        "power_capacity_amps": TEST_DEFAULTS["ZONE_POWER_AMPS"],
        "water_hookup_total": TEST_DEFAULTS["ZONE_WATER_HOOKUPS"],
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "label": "N-01",
        "power_outlet_max_amps": TEST_DEFAULTS["BOOTH_OUTLET_AMPS"],
        "has_water_hookup": False,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(application_id, booth_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "booth_id": booth_id,
        "power_draw_amps": TEST_DEFAULTS["POWER_DRAW_AMPS"],
        "requires_water": False,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "type": "HEALTH_PREOPEN",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(festival_id, **overrides) -> dict:
    defaults = {
        "festival_id": festival_id,
        "gate": "GATE_A",
        "window_start": "2026-07-10T08:00:00Z",
        "window_end": "2026-07-10T11:00:00Z",
        "max_vehicles": TEST_DEFAULTS["SLOT_MAX_VEHICLES"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(assignment_id, slot_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "slot_id": slot_id,
        "vehicle_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "amount_cents": 100000,
        "occurred_at": IN_WINDOW_SALE_ISO,
        "idempotency_key": "key-1",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(assignment_id, **overrides) -> dict:
    defaults = {"assignment_id": assignment_id}
    defaults.update(overrides)
    return defaults


def create_fine_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "type": "WASTE_SORTING",
        "amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults
