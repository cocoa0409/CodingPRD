"""Payload factories — one per creatable resource, input fields only.

Only `source: input` fields are set here; system-managed fields are minted
server-side.
"""

from .constants import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START


def create_counterparty_payload(**overrides) -> dict:
    defaults = {
        "counterparty_ref": "SUP-TEST",
        "legal_name": "Test Supplier Co",
        "counterparty_kind": "SUPPLIER",
        "credit_limit_usd": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_ref": "C-TEST",
        "pricing_mode": "DIFFERENTIAL_PTBF",
        "coffee_grade": "SHB",
        "total_lbs": 10000,
        "differential_usd_per_lb": 0.25,
        "delivery_window_start": DEFAULT_WINDOW_START,
        "delivery_window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_price_fix_payload(fix_lbs, futures_price_usd_per_lb,
                              expected_contract_version, **overrides) -> dict:
    payload = {
        "fix_lbs": fix_lbs,
        "futures_price_usd_per_lb": futures_price_usd_per_lb,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def short_close_payload(expected_contract_version) -> dict:
    return {"expected_contract_version": expected_contract_version}


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "shipment_ref": "SH-TEST",
        "planned_lbs": 1000,
        "scheduled_arrival": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def receive_shipment_payload(**overrides) -> dict:
    defaults = {
        "received_lbs": 1000,
        "lot_code": "LOT-TEST",
        "moisture_pct": 11.0,
        "warehouse_location": "WH-A",
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(outcome="ACCEPT", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_financing_line_payload(**overrides) -> dict:
    defaults = {
        "lender_name": "Test Bank",
        "facility_limit_usd": 100000,
        "advance_rate_pct": 0.50,
    }
    defaults.update(overrides)
    return defaults


def create_financing_reserve_payload(green_lot_id, reserved_lbs, **overrides) -> dict:
    payload = {
        "green_lot_id": green_lot_id,
        "reserved_lbs": reserved_lbs,
    }
    payload.update(overrides)
    return payload


def create_roast_profile_payload(**overrides) -> dict:
    defaults = {
        "profile_code": "RP-STD",
        "charge_temp_c": 200,
        "target_drop_temp_c": 210,
        "expected_yield_loss_pct": 0.16,
        "shrinkage_alert_band_pct": 0.02,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(target_roast_profile_id, **overrides) -> dict:
    defaults = {
        "sku": "P-TEST",
        "display_name": "Test Product",
        "channel": "WHOLESALE",
        "target_roast_profile_id": target_roast_profile_id,
        "freshness_days": 30,
    }
    defaults.update(overrides)
    return defaults


def add_recipe_component_payload(**overrides) -> dict:
    defaults = {
        "required_grade": "SHB",
        "component_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def approve_recipe_payload(expected_product_version) -> dict:
    return {"expected_product_version": expected_product_version}


def create_roast_batch_payload(product_id, recipe_id, scheduled_green_lbs,
                                **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "recipe_id": recipe_id,
        "scheduled_green_lbs": scheduled_green_lbs,
    }
    payload.update(overrides)
    return payload


def finish_roast_batch_payload(actual_roasted_lbs) -> dict:
    return {"actual_roasted_lbs": actual_roasted_lbs}


def pack_roast_batch_payload(packed_lbs) -> dict:
    return {"packed_lbs": packed_lbs}


def create_cupping_session_payload(subject_kind, subject_id, panelist_count=3,
                                    **overrides) -> dict:
    defaults = {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "panelist_count": panelist_count,
        "score_aroma": 8.5,
        "score_flavor": 8.5,
        "score_aftertaste": 8.5,
        "score_acidity": 8.5,
        "score_body": 8.5,
        "score_balance": 8.5,
        "score_uniformity": 10.0,
        "score_clean_cup": 10.0,
        "score_sweetness": 10.0,
        "score_overall": 8.5,
        "defects_subtracted": 0,
    }
    defaults.update(overrides)
    return defaults


def create_fulfillment_order_payload(customer_counterparty_id, **overrides) -> dict:
    defaults = {
        "customer_counterparty_id": customer_counterparty_id,
        "channel": "WHOLESALE",
        "requested_ship_date": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def add_fulfillment_line_payload(finished_goods_lot_id, allocated_lbs,
                                  **overrides) -> dict:
    payload = {
        "finished_goods_lot_id": finished_goods_lot_id,
        "allocated_lbs": allocated_lbs,
    }
    payload.update(overrides)
    return payload


def create_futures_hedge_payload(**overrides) -> dict:
    defaults = {
        "hedge_side": "BUY_FUTURES",
        "hedge_lbs": 1000,
        "entry_price_usd_per_lb": 1.80,
    }
    defaults.update(overrides)
    return defaults


def lift_hedge_payload(exit_price_usd_per_lb) -> dict:
    return {"exit_price_usd_per_lb": exit_price_usd_per_lb}
