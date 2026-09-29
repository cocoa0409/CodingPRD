"""Costing, claim profile, production cost and tolerance bands (§1.3)."""

from decimal import Decimal

import constants as K
from db import db, rhu
from services import graph


def _unit_cost_cents(line):
    if line["component_type"] == "RAW_MATERIAL":
        material = db.materials.get(line["raw_material_id"])
        if material is None:
            return Decimal("0")
        return Decimal(material["cost_per_kg_cents"])
    sub = db.formulas.get(line["sub_formula_id"])
    if sub is None or sub.get("bench_cost_per_kg_cents") is None:
        return Decimal("0")
    return Decimal(sub["bench_cost_per_kg_cents"])


def apply_bench_cost(formula):
    """calculations.formula_bench_cost - round per line, then sum."""
    total = 0
    for line in graph.components_of(formula["id"]):
        unit = _unit_cost_cents(line)
        contribution = int(rhu(unit * line["weight_pct"] / Decimal(100), 0))
        line["contribution_cents"] = contribution
        total += contribution
    formula["bench_cost_per_kg_cents"] = total
    return total


def _volume_discount_pct(annual_volume_kg):
    if annual_volume_kg < K.VOLUME_TIER_1_KG:
        return K.DISCOUNT_TIER_1_PCT
    if annual_volume_kg < K.VOLUME_TIER_2_KG:
        return K.DISCOUNT_TIER_2_PCT
    return K.DISCOUNT_TIER_3_PCT


def apply_cost_in_use(formula, brief):
    """calculations.formula_cost_in_use - bench (gating) and firm variants."""
    bench = Decimal(formula["bench_cost_per_kg_cents"])
    dosage = brief["dosage_pct"]
    bench_ciu = int(rhu(bench * dosage * Decimal(10), 0))
    discount = _volume_discount_pct(brief["annual_volume_kg"])
    firm_per_kg = rhu(
        bench * (Decimal(1) - discount / Decimal(100))
        / (Decimal(1) - K.YIELD_LOSS_PCT / Decimal(100)), 0)
    firm_ciu = int(rhu(firm_per_kg * dosage * Decimal(10), 0))
    formula["bench_cost_in_use_cents_per_tonne"] = bench_ciu
    formula["firm_cost_in_use_cents_per_tonne"] = firm_ciu
    return bench_ciu, firm_ciu


def apply_claim_profile(formula):
    """calculations.formula_claim_profile - transitive allergens and claims."""
    leaves = graph.leaf_materials(formula["id"])
    allergens = set()
    natural_ok = True
    kosher_ok = True
    halal_ok = True
    for material_id in leaves:
        material = db.materials.get(material_id)
        if material is None:
            continue
        for code in material.get("allergen_codes") or []:
            allergens.add(code)
        if material["natural_status"] not in K.NATURAL_OK:
            natural_ok = False
        if not graph.substantiated(material_id, "NATURAL"):
            natural_ok = False
        if not graph.substantiated(material_id, "KOSHER"):
            kosher_ok = False
        if not graph.substantiated(material_id, "HALAL"):
            halal_ok = False
    formula["allergen_codes"] = sorted(allergens)
    formula["natural_claim_eligible"] = bool(natural_ok)
    formula["kosher_eligible"] = bool(kosher_ok)
    formula["halal_eligible"] = bool(halal_ok)
    formula["cost_stale"] = False


def clear_cost_and_claim(formula):
    """COSTED/REWORK_REQUIRED -> DRAFT fallback (§3.3)."""
    formula["bench_cost_per_kg_cents"] = None
    formula["bench_cost_in_use_cents_per_tonne"] = None
    formula["firm_cost_in_use_cents_per_tonne"] = None
    formula["allergen_codes"] = []
    formula["natural_claim_eligible"] = None
    formula["kosher_eligible"] = None
    formula["halal_eligible"] = None
    formula["cost_stale"] = False
    for line in graph.components_of(formula["id"]):
        line["contribution_cents"] = None


# --- production costing (§3.9) ----------------------------------------------

def _fee_pct(material_cost_cents):
    if material_cost_cents < K.FEE_TIER_1_CENTS:
        return K.FEE_PCT_SMALL
    if material_cost_cents < K.FEE_TIER_2_CENTS:
        return K.FEE_PCT_MEDIUM
    return K.FEE_PCT_LARGE


def apply_production_cost(batch, formula):
    target_kg = Decimal(batch["target_kg"])
    bench = Decimal(formula["bench_cost_per_kg_cents"] or 0)
    material_cost = int(rhu(bench * target_kg, 0))          # step 1
    fee_pct = _fee_pct(material_cost)                        # step 2
    fee_cents = int(rhu(Decimal(material_cost) * fee_pct / Decimal(100), 0))  # 3
    batch_total = material_cost + fee_cents + K.QA_RELEASE_FEE_CENTS          # 4
    per_kg = int(rhu(Decimal(batch_total) / target_kg, 0))                    # 5
    batch["material_cost_cents"] = material_cost
    batch["compounding_fee_pct"] = fee_pct
    batch["compounding_fee_cents"] = fee_cents
    batch["batch_total_cents"] = batch_total
    batch["production_cost_per_kg_cents"] = per_kg


def _scale_factor(target_kg):
    if target_kg < K.SCALE_TIER_1_KG:
        return K.SCALE_FACTOR_SMALL
    if target_kg < K.SCALE_TIER_2_KG:
        return K.SCALE_FACTOR_MEDIUM
    return K.SCALE_FACTOR_LARGE


def build_tolerance_spec(batch, formula):
    scale = _scale_factor(batch["target_kg"])
    spec = []
    for line in graph.components_of(formula["id"]):
        weight = line["weight_pct"]
        base = weight * K.RELATIVE_BAND_FACTOR
        if base < K.MIN_BAND_PCT:
            base = K.MIN_BAND_PCT
        if line["component_type"] == "SUB_FORMULA":
            potency = K.POTENCY_FACTOR_SUB_FORMULA
            headroom = K.MAX_BAND_PCT
        else:
            material = db.materials.get(line["raw_material_id"])
            if material is not None and material["potency_class"] == "HIGH_IMPACT":
                potency = K.POTENCY_FACTOR_HIGH_IMPACT
            else:
                potency = K.POTENCY_FACTOR_STANDARD
            ceiling = Decimal(material["max_use_ppm"]) / Decimal(10000) \
                if material is not None else Decimal(0)
            headroom = ceiling - weight
            if headroom < Decimal("0.0000"):
                headroom = Decimal("0.0000")
        geometric = base * potency * scale
        if geometric > K.MAX_BAND_PCT:
            geometric = K.MAX_BAND_PCT
        band = geometric if geometric < headroom else headroom
        spec.append({
            "component_id": line["id"],
            "weight_pct": weight,
            "band_pct": rhu(band, 4),
        })
    batch["tolerance_spec"] = spec
    return spec
