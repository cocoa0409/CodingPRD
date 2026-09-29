"""Hazard classification, commodity escalation and the demand snapshot (PRD 3.2, 3.3)."""
from decimal import Decimal

from utils import _dec, floor_div_steps, rhu

# ascending severity order
HAZARD_CLASSES = ["LIGHT", "ORDINARY_1", "ORDINARY_2", "EXTRA_1", "EXTRA_2"]
COMMODITY_CLASSES = ["CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV", "GROUP_A_PLASTIC"]
SPRINKLER_SYSTEM_TYPES = ["WET", "DRY", "PREACTION"]

BASE_FIGURES = {
    "LIGHT": (Decimal("0.100"), Decimal("1500")),
    "ORDINARY_1": (Decimal("0.150"), Decimal("1500")),
    "ORDINARY_2": (Decimal("0.200"), Decimal("1500")),
    "EXTRA_1": (Decimal("0.300"), Decimal("2500")),
    "EXTRA_2": (Decimal("0.400"), Decimal("2500")),
}

HOSE_ALLOWANCE = {
    "LIGHT": 100.0,
    "ORDINARY_1": 250.0,
    "ORDINARY_2": 250.0,
    "EXTRA_1": 500.0,
    "EXTRA_2": 500.0,
}

PLASTIC_HEIGHT_FT = Decimal("12")
CLASS_IV_HEIGHT_FT = Decimal("15")
DRY_AREA_MULTIPLIER = Decimal("1.30")
SLOPE_AREA_MULTIPLIER = Decimal("1.30")
SLOPE_THRESHOLD_PCT = Decimal("16.7")
HIGH_CEILING_THRESHOLD_FT = Decimal("30")
CEILING_STEP_FT = Decimal("5")
DENSITY_STEP = Decimal("0.02")
DENSITY_BUMP_CAP = Decimal("0.06")


def escalate(hazard_class, commodity_class, storage_height_ft):
    """Step one: commodity escalation, at most a single position (PRD 3.2)."""
    index = HAZARD_CLASSES.index(hazard_class)
    height = _dec(storage_height_ft)
    bump = 0
    if commodity_class == "GROUP_A_PLASTIC" and height > PLASTIC_HEIGHT_FT:
        bump = 1
    elif commodity_class == "CLASS_IV" and height > CLASS_IV_HEIGHT_FT:
        bump = 1
    return HAZARD_CLASSES[min(index + bump, len(HAZARD_CLASSES) - 1)]


def classify(inputs):
    """The three ordered classification steps.

    Returns effective_hazard_class, design_density, design_area_sqft and
    hose_allowance_gpm for the supplied hazard-area inputs.
    """
    effective = escalate(
        inputs["hazard_class"], inputs["commodity_class"], inputs["storage_height_ft"]
    )
    density, area = BASE_FIGURES[effective]

    # step two: design area adjustments, multiplicatively and in this order
    if inputs["sprinkler_system_type"] in ("DRY", "PREACTION"):
        area = area * DRY_AREA_MULTIPLIER
    if _dec(inputs.get("ceiling_slope_pct") or 0.0) > SLOPE_THRESHOLD_PCT:
        area = area * SLOPE_AREA_MULTIPLIER

    # step three: the high-ceiling density bump
    ceiling = _dec(inputs["ceiling_height_ft"])
    if ceiling > HIGH_CEILING_THRESHOLD_FT:
        steps = floor_div_steps(ceiling - HIGH_CEILING_THRESHOLD_FT, CEILING_STEP_FT)
        addition = DENSITY_STEP * Decimal(steps)
        if addition > DENSITY_BUMP_CAP:
            addition = DENSITY_BUMP_CAP
        density = density + addition

    gross = _dec(inputs["area_sqft"])
    rounded_area = _dec(rhu(area, 0))
    capped = rounded_area if rounded_area <= gross else gross
    return {
        "effective_hazard_class": effective,
        "design_density": rhu(density, 3),
        "design_area_sqft": float(capped),
        "hose_allowance_gpm": HOSE_ALLOWANCE[effective],
    }


OVERDISCHARGE_FACTOR = Decimal("1.10")
OPENING_PENALTY_FACTOR = Decimal("0.25")
MIN_ENCLOSURE_RATING_HOURS = Decimal("1.0")
METHODS = ["AREA_DENSITY", "ROOM_DESIGN"]


def room_design_admissible(area):
    """The three ROOM_DESIGN admissibility conditions (PRD 3.3)."""
    room = area.get("room_area_sqft")
    if room is None:
        return False
    if _dec(room) > _dec(area["design_area_sqft"]):
        return False
    rating = area.get("enclosure_rating_hours")
    if rating is None or _dec(rating) < MIN_ENCLOSURE_RATING_HOURS:
        return False
    return True


def demand_snapshot(area, method):
    """design_flow_gpm, hose_allowance_gpm, room_design_penalty_gpm and the total."""
    density = _dec(area["design_density"])
    if method == "ROOM_DESIGN":
        basis = _dec(area["room_area_sqft"])
        if area.get("room_has_unprotected_opening"):
            penalty = rhu(density * OPENING_PENALTY_FACTOR * basis, 1)
        else:
            penalty = 0.0
    else:
        basis = _dec(area["design_area_sqft"])
        penalty = 0.0
    design_flow = rhu(density * basis * OVERDISCHARGE_FACTOR + _dec(penalty), 1)
    hose = float(area["hose_allowance_gpm"])
    return {
        "design_flow_gpm": design_flow,
        "hose_allowance_gpm": hose,
        "room_design_penalty_gpm": penalty,
        "hazard_total_demand_gpm": rhu(_dec(design_flow) + _dec(hose), 1),
    }
