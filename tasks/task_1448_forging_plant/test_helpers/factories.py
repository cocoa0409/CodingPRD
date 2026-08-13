"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    ALLOY_4140,
    DEFAULT_CHARGE_TEMP_F,
    DEFAULT_SOAK_MINUTES,
    FURNACE_DEFAULT_CAPACITY_LBS,
    HEAT_DEFAULTS,
    SURCHARGE_4140_2026_08,
    WORK_ORDER_DEFAULTS,
)


def alloy_spec_payload(**overrides) -> dict:
    payload = dict(ALLOY_4140)
    payload.update(overrides)
    return payload


def mill_heat_payload(alloy_spec_id, heat_number="H-1001", **overrides) -> dict:
    payload = {
        "heat_number": heat_number,
        "alloy_spec_id": alloy_spec_id,
        "mill_name": HEAT_DEFAULTS["mill_name"],
        "received_weight_lbs": HEAT_DEFAULTS["received_weight_lbs"],
        "bar_lbs_per_in": HEAT_DEFAULTS["bar_lbs_per_in"],
    }
    payload.update(overrides)
    return payload


def verify_cert_payload(carbon_pct=0.40, manganese_pct=0.90) -> dict:
    return {"carbon_pct": carbon_pct, "manganese_pct": manganese_pct}


def cut_lines_payload(cut_length_in=20.0, quantity=1) -> dict:
    return {"cuts": [{"cut_length_in": cut_length_in, "quantity": quantity}]}


def furnace_payload(furnace_code="FUR-1", capacity_lbs=FURNACE_DEFAULT_CAPACITY_LBS) -> dict:
    return {"furnace_code": furnace_code, "capacity_lbs": capacity_lbs}


def furnace_charge_payload(
    furnace_id,
    billet_ids,
    planned_load_start,
    planned_unload,
    target_temp_f=DEFAULT_CHARGE_TEMP_F,
    soak_minutes=DEFAULT_SOAK_MINUTES,
) -> dict:
    return {
        "furnace_id": furnace_id,
        "billet_ids": list(billet_ids),
        "target_temp_f": target_temp_f,
        "soak_minutes": soak_minutes,
        "planned_load_start": planned_load_start,
        "planned_unload": planned_unload,
    }


def die_set_payload(die_set_code="DIE-1", part_family="FLG-4",
                    wear_limit_hits=300, max_resinks=2) -> dict:
    return {
        "die_set_code": die_set_code,
        "part_family": part_family,
        "wear_limit_hits": wear_limit_hits,
        "max_resinks": max_resinks,
    }


def work_center_payload(code="WC-1", type="PRESS", rated_tonnage=500) -> dict:
    return {"code": code, "type": type, "rated_tonnage": rated_tonnage}


def work_order_payload(alloy_spec_id, order_number="WO-1", **overrides) -> dict:
    payload = {
        "order_number": order_number,
        "customer_name": WORK_ORDER_DEFAULTS["customer_name"],
        "alloy_spec_id": alloy_spec_id,
        "part_number": WORK_ORDER_DEFAULTS["part_number"],
        "ordered_qty": WORK_ORDER_DEFAULTS["ordered_qty"],
        "part_net_weight_lbs": WORK_ORDER_DEFAULTS["part_net_weight_lbs"],
        "billet_weight_lbs": WORK_ORDER_DEFAULTS["billet_weight_lbs"],
        "projected_area_in2": WORK_ORDER_DEFAULTS["projected_area_in2"],
        "required_process": WORK_ORDER_DEFAULTS["required_process"],
        "price_tier1_limit_tons": WORK_ORDER_DEFAULTS["price_tier1_limit_tons"],
        "price_tier1_cents_per_ton": WORK_ORDER_DEFAULTS["price_tier1_cents_per_ton"],
        "price_tier2_limit_tons": WORK_ORDER_DEFAULTS["price_tier2_limit_tons"],
        "price_tier2_cents_per_ton": WORK_ORDER_DEFAULTS["price_tier2_cents_per_ton"],
        "price_tier3_cents_per_ton": WORK_ORDER_DEFAULTS["price_tier3_cents_per_ton"],
        "scrap_recovery_rate_cents_per_lb": WORK_ORDER_DEFAULTS["scrap_recovery_rate_cents_per_lb"],
    }
    payload.update(overrides)
    return payload


def forge_run_payload(work_order_id, die_set_id, planned_start, planned_end,
                      planned_qty, expected_work_order_version, work_center_id=None) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "die_set_id": die_set_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "planned_qty": planned_qty,
        "expected_work_order_version": expected_work_order_version,
    }
    if work_center_id is not None:
        payload["work_center_id"] = work_center_id
    return payload


def forge_heat_payload(furnace_charge_id, billet_ids, parts_good, parts_scrapped=0) -> dict:
    return {
        "furnace_charge_id": furnace_charge_id,
        "billet_ids": list(billet_ids),
        "parts_good": parts_good,
        "parts_scrapped": parts_scrapped,
    }


def trim_record_payload(gross_as_forged_lbs, net_trimmed_lbs, pierce_loss_lbs) -> dict:
    return {
        "gross_as_forged_lbs": gross_as_forged_lbs,
        "net_trimmed_lbs": net_trimmed_lbs,
        "pierce_loss_lbs": pierce_loss_lbs,
    }


def quality_cert_submit_payload(grain_flow_rating=6, macro_etch_result="PASS") -> dict:
    return {"grain_flow_rating": grain_flow_rating, "macro_etch_result": macro_etch_result}


def surcharge_index_payload(alloy_spec_id, **overrides) -> dict:
    payload = {
        "alloy_spec_id": alloy_spec_id,
        "effective_month": SURCHARGE_4140_2026_08["effective_month"],
        "surcharge_cents_per_ton": SURCHARGE_4140_2026_08["surcharge_cents_per_ton"],
        "energy_pct": SURCHARGE_4140_2026_08["energy_pct"],
    }
    payload.update(overrides)
    return payload


def invoice_payload(expected_work_order_version) -> dict:
    return {"expected_work_order_version": expected_work_order_version}
