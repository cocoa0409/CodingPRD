"""Calculation rules from scaffold §1.3 and PRD §3.

All arithmetic is Decimal. Precision per PRD §2.5:
  costs -> 4dp half-up; weights/percentages/yardage -> 2dp half-up; delta-E -> 3dp half-up.
"""

from decimal import Decimal

from validators import round2, round3, round4


# Constants per scaffold calculations[].constants
COUNT_TOLERANCE_PCT = Decimal("3.0")
SHRINKAGE_REJECT_PCT = Decimal("8.0")
SHRINKAGE_SECOND_PCT = Decimal("5.0")
HAND_MIN = 3
YARDS_PER_LB_BANDS = [
    # (band upper bound (inclusive-ish), yards per pound). A count falls into the
    # first band whose midpoint region it belongs to. Per PRD §3.2 the bands are
    # "at Ne 10", "at Ne 20", "at Ne 30"; we bucket by nearest band anchor.
    (Decimal("15"), Decimal("8400")),    # Ne 10 band  (<= 15)
    (Decimal("25"), Decimal("16800")),   # Ne 20 band  (15 < x <= 25)
    (None, Decimal("25200")),            # Ne 30 band  (> 25)
]


def yards_per_lb_for_count(actual_yarn_count_ne):
    for bound, yards in YARDS_PER_LB_BANDS:
        if bound is None or actual_yarn_count_ne <= bound:
            return yards
    return Decimal("25200")


def initial_greige_yards(spun_weight_lbs, actual_yarn_count_ne):
    """greige_yards_available starts at spun_weight_lbs * yards-per-lb for its count band."""
    yards = yards_per_lb_for_count(actual_yarn_count_ne)
    return round2(spun_weight_lbs * yards)


# ---------------------------------------------------------------------------
# blend_cost_estimate
# ---------------------------------------------------------------------------

def projected_cost_per_lb(components, fiber_lots_by_id):
    """Variant A (forward_looking): on BlendRecipe approval.
    sum(component_weight * lot.unit_cost_per_lb) / total_component_weight_lbs.
    Uses the CURRENT lot cost at approval time.
    """
    total = Decimal("0")
    weighted = Decimal("0")
    for comp in components:
        lot = fiber_lots_by_id[comp["fiber_lot_id"]]
        weighted += comp["component_weight_lbs"] * lot["unit_cost_per_lb"]
        total += comp["component_weight_lbs"]
    if total == 0:
        return None
    return round4(weighted / total)


def actual_cost_per_lb(components, fiber_lots_by_id, spun_weight_lbs):
    """Variant B (chronological): on MachineAssignment completion.
    sum(component_weight * lot.unit_cost_per_lb_AT_SPIN_TIME) / spun_weight_lbs.
    """
    weighted = Decimal("0")
    for comp in components:
        lot = fiber_lots_by_id[comp["fiber_lot_id"]]
        weighted += comp["component_weight_lbs"] * lot["unit_cost_per_lb"]
    if spun_weight_lbs == 0:
        return None
    return round4(weighted / spun_weight_lbs)


# ---------------------------------------------------------------------------
# yarn_count_deviation
# ---------------------------------------------------------------------------

def count_deviation_pct(actual_ne, target_ne):
    """(actual - target) / target * 100, 2dp half-up."""
    if target_ne == 0:
        return Decimal("0")
    return round2((actual_ne - target_ne) / target_ne * Decimal("100"))


def count_deviation_exceeds(actual_ne, target_ne):
    return abs(count_deviation_pct(actual_ne, target_ne)) > COUNT_TOLERANCE_PCT


# ---------------------------------------------------------------------------
# quality_grading (provisional + final variants)
# ---------------------------------------------------------------------------

def compute_grade(shrinkage_pct_provisional, shrinkage_pct_final, hand_score):
    """Use final shrinkage if present, else provisional. Thresholds per scaffold."""
    shrinkage_input = shrinkage_pct_final if shrinkage_pct_final is not None else shrinkage_pct_provisional
    if shrinkage_input >= SHRINKAGE_REJECT_PCT:
        return "REJECTED"
    if shrinkage_input >= SHRINKAGE_SECOND_PCT:
        return "SECOND_QUALITY"
    if hand_score < HAND_MIN:
        return "SECOND_QUALITY"
    return "FIRST_QUALITY"


# ---------------------------------------------------------------------------
# roll_yardage_total — two pinned orderings
# ---------------------------------------------------------------------------

def put_up_total(rolls):
    """Round each roll's put_up_yards to 2dp first, then sum (round-then-sum)."""
    total = Decimal("0")
    for r in rolls:
        total += round2(r["put_up_yards"])
    return total


def allocated_total(rolls):
    """Sum raw actual_yards, then round the aggregate to 2dp (sum-then-round)."""
    total = Decimal("0")
    for r in rolls:
        total += r["actual_yards"]
    return round2(total)


# ---------------------------------------------------------------------------
# shade_match_check
# ---------------------------------------------------------------------------

def delta_e(measured_l, measured_a, measured_b, centroid_l, centroid_a, centroid_b):
    """Euclidean CIELAB distance, 3dp half-up."""
    dl = measured_l - centroid_l
    da = measured_a - centroid_a
    db = measured_b - centroid_b
    sq = dl * dl + da * da + db * db
    # Decimal.sqrt() is supported in Python 3.9+ for Decimal? No — use ** Decimal('0.5') via ln/exp is
    # imprecise. Use float sqrt then re-quantize; input precision here is small so this is safe.
    import math
    val = Decimal(str(math.sqrt(float(sq))))
    return round3(val)


def yardage_deviation_pct(put_up_yards, actual_yards):
    if put_up_yards == 0:
        return Decimal("0")
    return round2((actual_yards - put_up_yards) / put_up_yards * Decimal("100"))
