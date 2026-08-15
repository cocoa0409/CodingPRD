"""All calculation rules from the scaffold, implemented exactly as specified."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORES
from util import (
    D, round2, ceil2, floor_int, num,
    HIGH_RISK_ALLERGENS,
)

HIGH_PROTEIN_MIN = D("10.0")
GOOD_SOURCE_MIN = D("5.0")
LOW_SUGAR_MAX_G_PER_BAR = D("4.0")
SWAB_LIMIT_PPM = D("20")
WET_CLEAN_STALENESS_MIN = 1440
BUFFER_MINUTES = {"NONE": 0, "DRY_CLEAN": 30, "WET_CLEAN": 60, "SWAB_VALIDATE": 90}
TRIM_PCT = D("0.04")
BARS_PER_CASE = 12
QUARTER_DAYS = 91
YIELD_TOLERANCE_PCT = D("5.00")
DAY_MINUTES = 1440


def bars_per_batch(revision, formula):
    """floor(batch_size_kg * 1000 / bar_weight_g)"""
    return floor_int(D(revision["batch_size_kg"]) * 1000 / D(formula["bar_weight_g"]))


def _protein_per_serving(revision, formula, line_pct):
    """Pinned rounding order: round each line contribution to 2dp FIRST, sum,
    divide by bars_per_batch and round 2dp, divide by servings and round 2dp.
    line_pct(line) -> Decimal protein fraction. Returns Decimal or None when
    bars_per_batch == 0 (treated as unsubstantiated)."""
    bpb = bars_per_batch(revision, formula)
    if bpb <= 0:
        return None
    total = Decimal("0")
    for line in revision["ingredient_lines"]:
        if not line.get("is_protein_contributor"):
            continue
        contribution = D(line["qty_kg_per_batch"]) * 1000 * line_pct(line)
        total += round2(contribution)
    per_bar = round2(total / bpb)
    per_serving = round2(per_bar / int(formula["serving_count_per_bar"]))
    return per_serving


def label_protein_per_serving(revision, formula):
    """LABEL variant: nominal assays."""
    def pct(line):
        ing = STORES["ingredients"][line["ingredient_id"]]
        return D(ing.get("nominal_protein_pct") or 0)
    return _protein_per_serving(revision, formula, pct)


def composite_protein_per_serving(revision, formula, run):
    """COMPOSITE variant: reserved-lot CoA weighted assays. Returns Decimal,
    or the string 'SHORTAGE' when a protein line has zero reserved kg."""
    allocs = run["reserved_lot_allocations"]

    def pct(line):
        line_allocs = [a for a in allocs if a["ingredient_id"] == line["ingredient_id"]]
        total_kg = sum((D(a["qty_kg"]) for a in line_allocs), Decimal("0"))
        if total_kg <= 0:
            raise ZeroReserved(line["ingredient_id"])
        weighted = Decimal("0")
        for a in line_allocs:
            lot = STORES["lots"][a["lot_id"]]
            weighted += D(a["qty_kg"]) * D(lot.get("coa_protein_pct") or 0)
        return weighted / total_kg

    try:
        return _protein_per_serving(revision, formula, pct)
    except ZeroReserved:
        return "SHORTAGE"


class ZeroReserved(Exception):
    pass


def nutrient_claims_satisfied(revision, protein_per_serving):
    """Whether the protein figure satisfies every NUTRIENT_CONTENT claim tag
    (HIGH_PROTEIN >= 10.0, GOOD_SOURCE_PROTEIN >= 5.0)."""
    if protein_per_serving is None or protein_per_serving == "SHORTAGE":
        return False
    for tag in revision.get("claim_tags", []):
        if tag == "HIGH_PROTEIN" and protein_per_serving < HIGH_PROTEIN_MIN:
            return False
        if tag == "GOOD_SOURCE_PROTEIN" and protein_per_serving < GOOD_SOURCE_MIN:
            return False
    return True


def sweetener_provisional_line(line, ingredient):
    """PROVISIONAL variant per line: ceil to 0.01 kg of qty*nominal/nominal."""
    return ceil2(D(line["qty_kg_per_batch"]))


def sweetener_provisional_total(revision):
    total = Decimal("0")
    for line in revision["ingredient_lines"]:
        ing = STORES["ingredients"][line["ingredient_id"]]
        if ing["category"] == "SWEETENER":
            total += sweetener_provisional_line(line, ing)
    return round2(total)


def sweetener_final_line(line, run):
    """FINAL variant per line: ceil0.01(qty * nominal / reserved-weighted CoA
    factor). Returns Decimal or 'SHORTAGE' when nothing is reserved."""
    ing = STORES["ingredients"][line["ingredient_id"]]
    line_allocs = [a for a in run["reserved_lot_allocations"]
                   if a["ingredient_id"] == line["ingredient_id"]]
    total_kg = sum((D(a["qty_kg"]) for a in line_allocs), Decimal("0"))
    if total_kg <= 0:
        return "SHORTAGE"
    weighted = Decimal("0")
    for a in line_allocs:
        lot = STORES["lots"][a["lot_id"]]
        weighted += D(a["qty_kg"]) * D(lot.get("coa_sweetness_factor") or 0)
    factor = weighted / total_kg
    return ceil2(D(line["qty_kg_per_batch"]) * D(ing["nominal_sweetness_factor"]) / factor)


def agreement_quote(agreement, cases):
    """Tiered pricing. Returns (total_cents:int, per_case_cents:int)."""
    tiers = agreement["tier_breaks"]
    if agreement["pricing_mode"] == "MARGINAL":
        prev = 0
        total = 0
        for tier in tiers:
            qty = max(0, min(cases, int(tier["upto_cases"])) - prev)
            total += qty * int(tier["rate_cents_per_case"])
            prev = int(tier["upto_cases"])
    else:  # AVERAGE: single reached tier's rate applies to all cases
        total = None
        for tier in tiers:
            if cases <= int(tier["upto_cases"]):
                total = cases * int(tier["rate_cents_per_case"])
                break
        if total is None:  # pragma: no cover - final tier is 999999999
            total = cases * int(tiers[-1]["rate_cents_per_case"])
    # per_case_cents = round_half_up(total_cents / cases, 0) as integer
    per_case = int((D(total) / D(cases)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total, per_case


def changeover_level(from_profile, to_profile, minutes_since_wet_clean):
    """Changeover level matrix. minutes_since_wet_clean may be None (never)."""
    from_set = set(from_profile or [])
    to_set = set(to_profile or [])
    carryover = from_set - to_set
    if not from_set:
        return "NONE"
    if not carryover:
        return "DRY_CLEAN"
    if (carryover & HIGH_RISK_ALLERGENS) or len(carryover) >= 2:
        return "SWAB_VALIDATE"
    if minutes_since_wet_clean is None or minutes_since_wet_clean > WET_CLEAN_STALENESS_MIN:
        return "SWAB_VALIDATE"
    return "WET_CLEAN"


def cut_plan_cases(revision, line, formula):
    """Floor per slab BEFORE multiplying by slab count (pinned order)."""
    slab_count = floor_int(D(revision["batch_size_kg"]) / D(line["slab_weight_kg"]))
    bars_per_slab = floor_int(
        D(line["slab_weight_kg"]) * 1000 * (1 - TRIM_PCT) / D(formula["bar_weight_g"]))
    total_bars = bars_per_slab * slab_count
    return total_bars // BARS_PER_CASE


def hardness_projection(study):
    """Linear growth projection to expiry over RECORDED pulls.
    Returns (projected Decimal|None, pulls_used int)."""
    pulls = [p for p in STORES["pulls"].values()
             if p["study_id"] == study["id"] and p["status"] == "RECORDED"]
    pulls.sort(key=lambda p: (p["recorded_utc_dt"], p["pull_index"]))
    if not pulls:
        return None, 0
    if len(pulls) == 1:
        return round2(D(pulls[0]["hardness_n"])), 1
    first, last = pulls[0], pulls[-1]
    days_span = D((last["recorded_utc_dt"] - first["recorded_utc_dt"]).total_seconds()) / D(86400)
    shelf_days = D((study["expiry_utc_dt"] - study["start_utc_dt"]).total_seconds()) / D(86400)
    if days_span <= 0:
        return round2(D(last["hardness_n"])), len(pulls)
    rate = (D(last["hardness_n"]) - D(first["hardness_n"])) / days_span
    return round2(D(first["hardness_n"]) + rate * shelf_days), len(pulls)


def yield_variance_pct(produced_cases, planned_cases):
    return round2((D(produced_cases) - D(planned_cases)) / D(planned_cases) * 100)


def agreement_rollup(agreement):
    """produced cases over RELEASED runs completed inside
    [quarter_start, quarter_start + 91 days)."""
    start = agreement["quarter_start_dt"]
    end = start + timedelta(days=QUARTER_DAYS)
    produced = 0
    for run in STORES["runs"].values():
        if run["agreement_id"] != agreement["id"]:
            continue
        if run["release_status"] != "RELEASED":
            continue
        completed = run.get("completed_utc_dt")
        if completed is None:
            continue
        if start <= completed < end:
            produced += int(run.get("produced_cases") or 0)
    shortfall = max(0, int(agreement["committed_cases_per_quarter"]) - produced)
    return produced, shortfall


def day_availability(line, day_start):
    """Occupancy of CONFIRMED slots over [day_start, day_start+1d)."""
    from datetime import timedelta as _td
    day_end = day_start + _td(days=1)
    occupied_seconds = 0
    buffered = 0
    for slot in STORES["slots"].values():
        if slot["line_id"] != line["id"] or slot["status"] != "CONFIRMED":
            continue
        lo = max(slot["start_utc_dt"], day_start)
        hi = min(slot["end_utc_dt"], day_end)
        if hi > lo:
            occupied_seconds += (hi - lo).total_seconds()
        if day_start <= slot["start_utc_dt"] < day_end:
            buffered += int(slot["buffer_minutes"])
    occupied = int(occupied_seconds // 60)
    free = DAY_MINUTES - occupied - buffered
    return occupied, buffered, free


def claim_substantiation_ok(revision, formula, claim_tag):
    """Per-claim substantiation predicate over the revision's computed fields."""
    if claim_tag == "HIGH_PROTEIN":
        v = revision.get("label_protein_g_per_serving")
        return v is not None and D(v) >= HIGH_PROTEIN_MIN
    if claim_tag == "GOOD_SOURCE_PROTEIN":
        v = revision.get("label_protein_g_per_serving")
        return v is not None and D(v) >= GOOD_SOURCE_MIN
    if claim_tag == "LOW_SUGAR":
        bpb = bars_per_batch(revision, formula)
        if bpb <= 0:
            return False
        total = Decimal("0")
        for line in revision["ingredient_lines"]:
            ing = STORES["ingredients"][line["ingredient_id"]]
            if ing["category"] == "SWEETENER":
                total += D(line["qty_kg_per_batch"]) * 1000
        sugar_g_per_bar = round2(total / bpb)
        return sugar_g_per_bar <= LOW_SUGAR_MAX_G_PER_BAR
    if claim_tag == "GLUTEN_FREE":
        return "WHEAT" not in (revision.get("allergen_profile") or [])
    return False
