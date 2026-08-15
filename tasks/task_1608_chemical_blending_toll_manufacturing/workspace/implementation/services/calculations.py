"""Calculation rules from SCAFFOLD Table 3."""
from decimal import Decimal

from services.common import (
    round_half_up_decimal,
    round_half_up_cents,
    as_float_3dp,
)

# Hazard severity order: FLAMMABLE > OXIDIZER > TOXIN > ACID > BASE > NON_HAZ
SEVERITY = {
    "FLAMMABLE": 5,
    "OXIDIZER": 4,
    "TOXIN": 3,
    "ACID": 2,
    "BASE": 1,
    "NON_HAZ": 0,
}

GHS_CLASSES = set(SEVERITY.keys())

ZONES = {"Z_FLAM", "Z_OXID", "Z_ACID", "Z_BASE", "Z_TOXIC", "Z_GENERAL"}

ZONE_ALLOWED = {
    "Z_FLAM": {"FLAMMABLE"},
    "Z_OXID": {"OXIDIZER"},
    "Z_ACID": {"ACID"},
    "Z_BASE": {"BASE"},
    "Z_TOXIC": {"TOXIN"},
    "Z_GENERAL": {"NON_HAZ"},
}

# Symmetric forbidden pairs
INCOMPATIBLE_PAIRS = {
    frozenset({"FLAMMABLE", "OXIDIZER"}),
    frozenset({"ACID", "BASE"}),
    frozenset({"TOXIN", "FLAMMABLE"}),
    frozenset({"TOXIN", "OXIDIZER"}),
}

RESIDUE_LIMIT_PPM = 50

PACKAGE_CAPACITY_L = {
    "DRUM_205L": 205,
    "IBC_1000L": 1000,
    "TOTE_500L": 500,
    "PAIL_20L": 20,
}

PLACARD_VOLUME_THRESHOLD_L = 454

PLACARD_CLASS_BY_GHS = {
    "FLAMMABLE": "CLASS_3_FLAMMABLE",
    "OXIDIZER": "CLASS_5_1_OXIDIZER",
    "TOXIN": "CLASS_6_1_TOXIC",
    "ACID": "CLASS_8_CORROSIVE",
    "BASE": "CLASS_8_CORROSIVE",
}


def zone_admits(ghs_class, zone):
    """True iff zone admits ghs_class."""
    allowed = ZONE_ALLOWED.get(zone)
    if allowed is None:
        return False
    return ghs_class in allowed


def ghs_pair_compatible(a, b):
    """True iff classes a and b are allowed to follow each other / co-locate."""
    if a is None or b is None:
        return True
    return frozenset({a, b}) not in INCOMPATIBLE_PAIRS


def compute_highest_component_ghs(components, material_code_to_ghs):
    """Pick highest-severity GHS class across components. Ties broken by smallest charge_order."""
    if not components:
        return None
    best = None
    best_sev = -1
    best_order = None
    for comp in sorted(components, key=lambda c: c.get("charge_order", 0)):
        mc = comp.get("material_code")
        ghs = material_code_to_ghs.get(mc)
        if ghs is None:
            # if material code has no lot, treat as NON_HAZ severity 0? PRD says
            # every lot of a given material_code shares the same ghS_class.
            # If no lot exists, we skip this component for hazard profiling.
            continue
        sev = SEVERITY.get(ghs, -1)
        co = comp.get("charge_order")
        if sev > best_sev or (sev == best_sev and best_order is not None and co < best_order):
            best = ghs
            best_sev = sev
            best_order = co
    return best


def compute_theoretical_output_kg(batch_size_l, target_density_kg_per_l, theoretical_yield_pct):
    """batch_size_l * density * (yield_pct/100), rounded half-up to 3dp."""
    d = Decimal(str(batch_size_l)) * Decimal(str(target_density_kg_per_l)) * (
        Decimal(str(theoretical_yield_pct)) / Decimal(100)
    )
    return as_float_3dp(d)


def compute_density_corrected_output_l(actual_output_kg, target_density_kg_per_l):
    d = Decimal(str(actual_output_kg)) / Decimal(str(target_density_kg_per_l))
    return as_float_3dp(d)


def compute_yield_variance_pct(actual_output_kg, theoretical_output_kg):
    """100 * (actual - theo) / theo. 3dp round-half-up."""
    theo = Decimal(str(theoretical_output_kg))
    if theo == 0:
        # Avoid div-by-zero; return 0 by convention.
        return 0.0
    diff = Decimal(str(actual_output_kg)) - theo
    v = (Decimal(100) * diff) / theo
    return as_float_3dp(v)


def price_batch_job(pricing_agreement, batch, variant):
    """
    variant: "PROVISIONAL" or "FINAL".
    Returns integer cents.
    """
    pa = pricing_agreement
    theo_kg = Decimal(str(batch["theoretical_output_kg"]))
    if pa["pricing_mode"] == "TOLLING_FEE":
        base = Decimal(pa["tolling_base_fee_cents"]) + Decimal(pa["tolling_per_kg_cents"]) * theo_kg
        return round_half_up_cents(base)
    # FORMULATED_PRICE
    if variant == "PROVISIONAL":
        ref_kg = theo_kg
    else:
        ref_kg = Decimal(str(batch["actual_output_kg"]))
    base = Decimal(pa["formulated_price_per_kg_cents"]) * ref_kg
    if variant == "FINAL" and batch["actual_output_kg"] is not None:
        actual = Decimal(str(batch["actual_output_kg"]))
        if actual > theo_kg:
            over_kg = actual - theo_kg
            credit = over_kg * Decimal(pa["formulated_price_per_kg_cents"]) * (
                Decimal(pa["over_yield_split_pct"]) / Decimal(100)
            )
            base = base - credit
    return round_half_up_cents(base)


def compute_placard(ghs_classification, package_type, package_count):
    """Returns (total_volume_l, placard_required, placard_class)."""
    cap = PACKAGE_CAPACITY_L[package_type]
    total_volume_l = int(package_count) * cap
    placard_required = (ghs_classification != "NON_HAZ") and (total_volume_l >= PLACARD_VOLUME_THRESHOLD_L)
    if placard_required:
        placard_class = PLACARD_CLASS_BY_GHS.get(ghs_classification)
    else:
        placard_class = None
    return total_volume_l, placard_required, placard_class


def compute_authoring_consistency_flag(ghs_classification, signal_word, hazard_statements, snapshot_ghs):
    """Per PRD §3.7: all three must hold."""
    if ghs_classification != snapshot_ghs:
        return False
    if ghs_classification in {"FLAMMABLE", "OXIDIZER", "TOXIN"}:
        if signal_word != "DANGER":
            return False
    else:
        if signal_word not in {"WARNING", "NONE"}:
            return False
    if ghs_classification != "NON_HAZ":
        if not hazard_statements:
            return False
    return True


def ceil_l(value_l):
    """Ceiling to whole litres."""
    d = Decimal(str(value_l))
    return int(d.to_integral_value(rounding="ROUND_CEILING"))
