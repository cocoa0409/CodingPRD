"""Calculation rules (PRD §2.7, §3.5-§3.8): scores, deductions, ranking,
ticket totals, warm-up geometry. All point math uses Decimal; exactly one
round-half-up to 2dp after the weighted sum and scaling.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from store import db, set_fields

CATEGORIES = ("building_difficulty", "building_execution",
              "tumbling_difficulty", "overall_impression")
WEIGHTS = {
    "building_difficulty": Decimal("0.30"),
    "building_execution": Decimal("0.30"),
    "tumbling_difficulty": Decimal("0.20"),
    "overall_impression": Decimal("0.20"),
}
SCORE_SCALE = Decimal("10")
TRIM_MIN_PANEL = 5
PROVISIONAL_MIN_SHEETS = 2

TWO_DP = Decimal("0.01")

# Ticket pricing constants (integer cents)
ADVANCE_PRICE_CENTS = 1295
GATE_PRICE_CENTS = 1895
GROUP_MIN_QTY = 20
GROUP_DISCOUNT_PCT = Decimal("0.10")
HOLD_MINUTES = 15
MAX_PER_ORDER = 40
ADVANCE_CUTOFF_DAYS = 14

# Warm-up geometry
TRANSITION_BUFFER_S = 180
REST_S = 600

# Appeals / bids
APPEAL_WINDOW_MINUTES = 45
BID_ACCEPTANCE_HOURS = 72
AT_LARGE_PCT = Decimal("0.90")


def q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def submitted_sheets(performance_id):
    """Sheets feeding the score model. LOCKED sheets are frozen submissions
    (the panel's SUBMITTED sheets lock when the performance goes OFFICIAL),
    so they continue to count in post-official recomputes."""
    return [s for s in db.score_sheets.values()
            if s["performance_id"] == performance_id
            and s["status"] in ("SUBMITTED", "LOCKED")]


def category_values(performance_id, category, variant):
    vals = [Decimal(str(s[category])) for s in submitted_sheets(performance_id)]
    if variant == "OFFICIAL" and len(vals) >= TRIM_MIN_PANEL:
        # Remove exactly ONE highest and ONE lowest (single occurrence each).
        vals.remove(max(vals))
        vals.remove(min(vals))
    return vals


def category_avg(performance_id, category, variant):
    """Unrounded per-category mean (never rounded before the weighted sum)."""
    vals = category_values(performance_id, category, variant)
    if not vals:
        return Decimal("0")
    return sum(vals) / Decimal(len(vals))


def base_score(performance_id, variant):
    """Weighted base score; single round-half-up to 2dp after scaling.

    Returns None for PROVISIONAL when fewer than PROVISIONAL_MIN_SHEETS
    SUBMITTED sheets exist.
    """
    n = len(submitted_sheets(performance_id))
    if variant == "PROVISIONAL" and n < PROVISIONAL_MIN_SHEETS:
        return None
    if n == 0:
        return None
    total = Decimal("0")
    for cat in CATEGORIES:
        total += WEIGHTS[cat] * category_avg(performance_id, cat, variant)
    return q2(total * SCORE_SCALE)


def counted_deduction_points(performance_id, variant):
    if variant == "PROVISIONAL":
        statuses = ("APPLIED", "UNDER_APPEAL", "UPHELD")
    else:  # OFFICIAL excludes UNDER_APPEAL (unresolved)
        statuses = ("APPLIED", "UPHELD")
    total = Decimal("0")
    for d in db.deductions.values():
        if d["performance_id"] == performance_id and d["status"] in statuses:
            total += d["points"]
    return total


def final_score(performance_id, variant):
    base = base_score(performance_id, variant)
    if base is None:
        return None
    result = base - counted_deduction_points(performance_id, variant)
    return max(Decimal("0"), result)


def recompute_provisional(perf):
    """Refresh provisional_score while PERFORMED/SCORED (nulls if < 2 sheets)."""
    if perf["status"] not in ("PERFORMED", "SCORED"):
        return
    set_fields(perf, provisional_score=final_score(perf["id"], "PROVISIONAL"))


def deduction_points(quantity, rate_applied):
    """points = quantity * rate, round-half-up once to 2dp."""
    return q2(Decimal(quantity) * Decimal(str(rate_applied)))


# ---------------------------------------------------------------------------
# Division ranking
# ---------------------------------------------------------------------------

def recompute_ranking(division_id):
    """Total order over OFFICIAL performances; 1-based ranks written back."""
    ranked = [p for p in db.performances.values()
              if p["division_id"] == division_id and p["status"] == "OFFICIAL"]

    def key(p):
        ded_pts = counted_deduction_points(p["id"], "OFFICIAL")
        be_avg = category_avg(p["id"], "building_execution", "OFFICIAL")
        return (-p["official_score"], ded_pts, -be_avg,
                p["scheduled_start"], p["_seq"])

    ranked.sort(key=key)
    for idx, perf in enumerate(ranked, start=1):
        set_fields(perf, rank_in_division=idx)


# ---------------------------------------------------------------------------
# Ticket order totals
# ---------------------------------------------------------------------------

def ticket_pricing(event, quantity, created_at):
    """ORDER_LEVEL variant: discount on the order subtotal, rounded once."""
    from datetime import datetime, time as dtime
    start = event["start_date"]
    cutoff = datetime.combine(start - timedelta(days=ADVANCE_CUTOFF_DAYS),
                              dtime(0, 0, 0)).replace(tzinfo=created_at.tzinfo)
    tier = "ADVANCE" if created_at <= cutoff else "GATE"
    unit = ADVANCE_PRICE_CENTS if tier == "ADVANCE" else GATE_PRICE_CENTS
    subtotal = quantity * unit
    if quantity >= GROUP_MIN_QTY:
        discount = int((Decimal(subtotal) * GROUP_DISCOUNT_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        discount = 0
    return tier, unit, discount, subtotal - discount


# ---------------------------------------------------------------------------
# Warm-up geometry
# ---------------------------------------------------------------------------

def performance_pitch(division):
    return division["routine_time_limit_seconds"] + TRANSITION_BUFFER_S


def mats_required(division):
    pitch = performance_pitch(division)
    dur = division["warmup_duration_seconds"]
    return -(-dur // pitch)  # ceil division


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; pure adjacency does not overlap."""
    return a_start < b_end and b_start < a_end
