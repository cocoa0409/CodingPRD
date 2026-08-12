"""Payload factories — one per creatable resource, input fields only.

Canonical catalogue values mirror the design fixtures:
  TB1: NONFLAT / LATEX_EXTERIOR base, voc 80 g/L, water 40%, density 4.6,
       cost 1500c/gal, price 3200c/gal, shelf 24m, grind spec 25 um
  TB2: FLAT / LATEX_INTERIOR base, voc 30, water 50%, density 4.4,
       cost 1800c/gal, price 4100c/gal, shelf 24m, grind spec 20 um
  TB3: PRIMER / LATEX_INTERIOR base, voc 30, water 50%, density 4.6,
       cost 1800c/gal, price 4100c/gal, shelf 24m, grind spec 20 um
  C1:  MAG-7 colorant, 5 g voc/shot, 30c/shot, non-hazmat
  C2:  BLK-H colorant, 12 g voc/shot, 45c/shot, HAZMAT
"""

from .constants import WINDOW_JUN10_AM

_COUNTER = {"n": 0}


def _seq() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_customer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Sunbelt Paints AZ {n}",
        "home_state_code": "AZ",
        "annual_credit_cap_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_tint_base_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "base_code": f"B-100-{n}",
        "product_category": "NONFLAT",
        "base_family": "LATEX_EXTERIOR",
        "base_voc_gpl": 80,
        "water_fraction_pct": 40,
        "density_kg_per_gal": 4.6,
        "base_cost_per_gal_cents": 1500,
        "unit_price_per_gal_cents": 3200,
        "shelf_life_months": 24,
        "grind_spec_um": 25,
    }
    defaults.update(overrides)
    return defaults


def create_colorant_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "colorant_code": f"MAG-7-{n}",
        "voc_g_per_unit": 5,
        "cost_per_shot_cents": 30,
        "is_hazmat": False,
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(tint_base_id, colorant_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "formula_code": f"CLR-8841-{n}",
        "color_name": "Desert Dusk",
        "tint_base_id": tint_base_id,
        "is_custom": False,
        "target_delta_e": 0.8,
        "lines": [
            {"colorant_id": colorant_id, "shots_per_gallon": 4, "sequence": 1}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_voc_rule_payload(**overrides) -> dict:
    defaults = {
        "category": "NONFLAT",
        "state_code": "*",
        "max_voc_gpl": 250,
        "effective_from": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_mill_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "mill_code": f"M-1-{n}",
        "capacity_gallons": 200,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(formula_id, mill_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "mill_id": mill_id,
        "planned_gallons": 3,
        "mill_window_start": WINDOW_JUN10_AM[0],
        "mill_window_end": WINDOW_JUN10_AM[1],
    }
    defaults.update(overrides)
    return defaults


def dispersion_check_payload(grind_reading=18, **overrides) -> dict:
    defaults = {"grind_reading": grind_reading}
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {"kind": "THINNER", "quantity": 500}
    defaults.update(overrides)
    return defaults


def submit_qc_payload(actual_gallons=3, **overrides) -> dict:
    defaults = {"actual_gallons": actual_gallons}
    defaults.update(overrides)
    return defaults


def create_fill_payload(size_code="GALLON", actual_fill_g=4600, **overrides) -> dict:
    defaults = {"size_code": size_code, "actual_fill_g": actual_fill_g}
    defaults.update(overrides)
    return defaults


def complete_filling_payload(waste_gallons=0, **overrides) -> dict:
    defaults = {"waste_gallons": waste_gallons}
    defaults.update(overrides)
    return defaults


def create_color_match_payload(batch_id, measured_delta_e=0.42, **overrides) -> dict:
    defaults = {"batch_id": batch_id, "measured_delta_e": measured_delta_e}
    defaults.update(overrides)
    return defaults


def reweigh_payload(actual_fill_g=4600, **overrides) -> dict:
    defaults = {"actual_fill_g": actual_fill_g}
    defaults.update(overrides)
    return defaults


def ship_payload(order_id, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, formula_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "destination_state_code": "AZ",
        "rush_flag": False,
        "lines": [{"formula_id": formula_id, "gallons": 3, "size_code": "GALLON"}],
    }
    defaults.update(overrides)
    return defaults


def create_credit_claim_payload(customer_id, container_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "container_id": container_id,
        "claim_type": "FREEZE_DAMAGE",
        "invoice_value_cents": 40000,
        "claimed_exposure_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_disposal_request_payload(**overrides) -> dict:
    defaults = {"reason": "OBSOLETE_STOCK", "container_ids": []}
    defaults.update(overrides)
    return defaults
