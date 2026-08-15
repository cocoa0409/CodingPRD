"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS, WEEK_START_MONDAY, CUTOFF_WEDNESDAY

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_customer_payload(business_name=None, contact_email=None,
                            delivery_zone="NORTH", **overrides) -> dict:
    name = business_name or _unique("Resto")
    payload = {
        "business_name": name,
        "contact_email": contact_email or f"{name.lower()}@example.com",
        "delivery_zone": delivery_zone,
    }
    payload.update(overrides)
    return payload


def create_variety_payload(name=None, crop_category="MICROGREEN",
                           days_to_harvest=TEST_DEFAULTS["VARIETY_DAYS_TO_HARVEST"],
                           expected_yield_grams_per_tray=TEST_DEFAULTS["VARIETY_YIELD_GRAMS_PER_TRAY"],
                           listed_price_cents_per_kg=TEST_DEFAULTS["VARIETY_PRICE_CENTS_PER_KG"],
                           min_order_grams=TEST_DEFAULTS["VARIETY_MIN_ORDER_GRAMS"],
                           **overrides) -> dict:
    payload = {
        "name": name or _unique("Variety"),
        "crop_category": crop_category,
        "days_to_harvest": days_to_harvest,
        "expected_yield_grams_per_tray": expected_yield_grams_per_tray,
        "listed_price_cents_per_kg": listed_price_cents_per_kg,
        "min_order_grams": min_order_grams,
    }
    payload.update(overrides)
    return payload


def create_variety_trial_payload(variety_id, sow_date=WEEK_START_MONDAY,
                                 chef_panel_size=1, yield_score=7.0,
                                 **overrides) -> dict:
    payload = {
        "variety_id": variety_id,
        "sow_date": sow_date,
        "chef_panel_size": chef_panel_size,
        "yield_score": yield_score,
    }
    payload.update(overrides)
    return payload


def create_seed_lot_payload(variety_id, supplier_name="SeedCo", lot_code=None,
                            received_date="2026-08-01",
                            seeds_on_hand_grams=TEST_DEFAULTS["SEEDS_ON_HAND_GRAMS"],
                            **overrides) -> dict:
    payload = {
        "variety_id": variety_id,
        "supplier_name": supplier_name,
        "lot_code": lot_code or _unique("LOT"),
        "received_date": received_date,
        "seeds_on_hand_grams": seeds_on_hand_grams,
    }
    payload.update(overrides)
    return payload


def create_germination_test_payload(seed_lot_id, seeds_sown_count=100,
                                    **overrides) -> dict:
    payload = {"seed_lot_id": seed_lot_id, "seeds_sown_count": seeds_sown_count}
    payload.update(overrides)
    return payload


def create_food_safety_plan_payload(plan_code=None, water_test_current=True,
                                    sanitation_sop_version="SOP-1",
                                    **overrides) -> dict:
    payload = {
        "plan_code": plan_code or _unique("FSP"),
        "water_test_current": water_test_current,
        "sanitation_sop_version": sanitation_sop_version,
    }
    payload.update(overrides)
    return payload


def create_sanitation_log_payload(harvest_batch_id, surface_swab_passed=True,
                                  wash_water_ppm=100, logged_by="op-1",
                                  **overrides) -> dict:
    payload = {
        "harvest_batch_id": harvest_batch_id,
        "surface_swab_passed": surface_swab_passed,
        "wash_water_ppm": wash_water_ppm,
        "logged_by": logged_by,
    }
    payload.update(overrides)
    return payload


def create_crop_plan_payload(variety_id, planned_sow_date=WEEK_START_MONDAY,
                             planned_tray_count=TEST_DEFAULTS["PLANNED_TRAY_COUNT"],
                             seed_grams_required=TEST_DEFAULTS["SEED_GRAMS_REQUIRED"],
                             **overrides) -> dict:
    payload = {
        "variety_id": variety_id,
        "planned_sow_date": planned_sow_date,
        "planned_tray_count": planned_tray_count,
        "seed_grams_required": seed_grams_required,
    }
    payload.update(overrides)
    return payload


def sow_crop_plan_payload(seed_lot_id, expected_crop_plan_version,
                          **overrides) -> dict:
    payload = {
        "seed_lot_id": seed_lot_id,
        "expected_crop_plan_version": expected_crop_plan_version,
    }
    payload.update(overrides)
    return payload


def create_standing_order_payload(customer_id, effective_week_start=WEEK_START_MONDAY,
                                  change_cutoff_day=CUTOFF_WEDNESDAY,
                                  **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "effective_week_start": effective_week_start,
        "change_cutoff_day": change_cutoff_day,
    }
    payload.update(overrides)
    return payload


def add_order_line_payload(variety_id, qty_kg, expected_standing_order_version,
                           unit_price_cents_per_kg=None, **overrides) -> dict:
    payload = {
        "variety_id": variety_id,
        "qty_kg": qty_kg,
        "expected_standing_order_version": expected_standing_order_version,
    }
    if unit_price_cents_per_kg is not None:
        payload["unit_price_cents_per_kg"] = unit_price_cents_per_kg
    payload.update(overrides)
    return payload


def confirm_standing_order_payload(expected_standing_order_version) -> dict:
    return {"expected_standing_order_version": expected_standing_order_version}


def create_delivery_route_payload(route_code=None, service_date=TEST_DEFAULTS["ROUTE_SERVICE_DATE"],
                                  min_stop_subtotal_cents=TEST_DEFAULTS["MIN_STOP_SUBTOTAL_CENTS"],
                                  **overrides) -> dict:
    payload = {
        "route_code": route_code or _unique("R-N"),
        "service_date": service_date,
        "min_stop_subtotal_cents": min_stop_subtotal_cents,
    }
    payload.update(overrides)
    return payload


def add_delivery_stop_payload(customer_id, standing_order_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "standing_order_id": standing_order_id}
    payload.update(overrides)
    return payload


def create_spoilage_credit_payload(delivery_stop_id, order_item_id, credit_qty_kg,
                                   pricing_variant="ORIGINAL_PAPER",
                                   **overrides) -> dict:
    payload = {
        "delivery_stop_id": delivery_stop_id,
        "order_item_id": order_item_id,
        "credit_qty_kg": credit_qty_kg,
        "pricing_variant": pricing_variant,
    }
    payload.update(overrides)
    return payload


def create_surplus_listing_payload(variety_id, tray_batch_id, qty_kg,
                                   market_price_cents_per_kg,
                                   market_date="2026-08-15", **overrides) -> dict:
    payload = {
        "variety_id": variety_id,
        "tray_batch_id": tray_batch_id,
        "qty_kg": qty_kg,
        "market_price_cents_per_kg": market_price_cents_per_kg,
        "market_date": market_date,
    }
    payload.update(overrides)
    return payload
