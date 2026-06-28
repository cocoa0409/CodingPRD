"""Calculation rules from SCAFFOLD §1.3 / PRD §3. All monetary rounding is
round-half-up; rounding ORDER is pinned per the PRD where it matters."""
from decimal import Decimal, ROUND_HALF_UP

from common import D, round2, round_cents

# --- colony_strength_scoring constants ---
W_BROOD = 8
W_HONEY = 3
STRENGTH_MITE_PENALTY = 25
STRENGTH_QUEEN_BONUS = 10
MITE_TREATMENT_THRESHOLD = Decimal("3.0")
CONTRACT_GRADE_MIN = 60
BROOD_GROWTH_PER_WEEK = 2
MAX_BROOD_FRAMES = 20

# --- honey_yield constants ---
KG_PER_FRAME_ESTIMATE = Decimal("2.5")
EXTRACTION_LOSS_PCT = Decimal("0.04")

# --- pollination_payout constants ---
STRONG_MULT = Decimal("1.20")
SUB_GRADE_MULT = Decimal("0.50")
STRONG_BONUS_MIN = 80
SHORTFALL_PENALTY_CENTS = 5000
FULL_BONUS_CENTS = 10000

# --- honey_revenue constants ---
TIER1_MIN = 100000
TIER1_DISCOUNT = Decimal("0.05")
TIER2_MIN = 500000
TIER2_DISCOUNT = Decimal("0.10")


# ---------------------------------------------------------------------------
# colony_strength_scoring (PRD §3.3 / §3.5)
# ---------------------------------------------------------------------------
def _score(brood_frames, honey_frames, last_mite_count, queenright):
    """Shared weighted-scoring formula. last_mite_count may be None (no penalty).
    Returns an integer clamped to [0, 100]."""
    base = brood_frames * W_BROOD + honey_frames * W_HONEY
    mite_penalty = 0
    if last_mite_count is not None and D(last_mite_count) >= MITE_TREATMENT_THRESHOLD:
        mite_penalty = STRENGTH_MITE_PENALTY
    queen_bonus = STRENGTH_QUEEN_BONUS if queenright else 0
    raw = base - mite_penalty + queen_bonus
    if raw < 0:
        return 0
    if raw > 100:
        return 100
    return raw


def point_in_time_strength(brood_frames, honey_frames, last_mite_count, queen_status):
    """Variant point_in_time: brood/honey as observed at inspection, this mite reading."""
    return _score(brood_frames, honey_frames, last_mite_count,
                  queen_status == "QUEENRIGHT")


def forward_projected_strength(hive, bloom_start, clock):
    """Variant forward_projected: project brood_frames forward to bloom_start by
    BROOD_GROWTH_PER_WEEK frames/whole-week (floor of whole weeks), capped at
    MAX_BROOD_FRAMES, then score. Returns (score, grade)."""
    brood = hive["brood_frames"]
    if bloom_start > clock:
        delta_days = (bloom_start - clock).total_seconds() / 86400.0
        whole_weeks = int(delta_days // 7)
        if whole_weeks < 0:
            whole_weeks = 0
    else:
        whole_weeks = 0
    projected_brood = brood + whole_weeks * BROOD_GROWTH_PER_WEEK
    if projected_brood > MAX_BROOD_FRAMES:
        projected_brood = MAX_BROOD_FRAMES
    score = _score(projected_brood, hive["honey_frames"], hive.get("last_mite_count"),
                   hive["queen_status"] == "QUEENRIGHT")
    grade = "CONTRACT_GRADE" if score >= CONTRACT_GRADE_MIN else "SUB_GRADE"
    return score, grade


# ---------------------------------------------------------------------------
# honey_yield (PRD §3.7)
# ---------------------------------------------------------------------------
def provisional_yield(total_frames_pulled):
    """Sum of RECORDED frames_pulled * 2.5 kg/frame, round half-up to 2 dp."""
    return round2(D(total_frames_pulled) * KG_PER_FRAME_ESTIMATE)


def final_yield(gross_weight_kg):
    """gross_weight_kg * (1 - 0.04), round half-up to 2 dp."""
    return round2(D(gross_weight_kg) * (Decimal("1") - EXTRACTION_LOSS_PCT))


# ---------------------------------------------------------------------------
# pollination_payout (PRD §3.6)
# ---------------------------------------------------------------------------
def pollination_payout(confirmed_placements, base_rate_cents,
                       required_strong_hives, placed_strong_hives):
    """Per-confirmed-placement rate with strength tier multiplier and aggregate
    bonus/penalty. Round each per-hive amount BEFORE summing."""
    per_hive = []
    base = D(base_rate_cents)
    for p in confirmed_placements:
        if p["grade"] == "CONTRACT_GRADE":
            if p.get("contract_rated_strength") is not None and \
                    p["contract_rated_strength"] >= STRONG_BONUS_MIN:
                mult = STRONG_MULT
            else:
                mult = Decimal("1.0")
        else:
            mult = SUB_GRADE_MULT
        per_hive.append(round_cents(base * mult))
    subtotal = sum(per_hive)
    shortfall = max(0, required_strong_hives - placed_strong_hives)
    penalty = shortfall * SHORTFALL_PENALTY_CENTS
    fulfillment_bonus = FULL_BONUS_CENTS if placed_strong_hives >= required_strong_hives else 0
    return max(0, subtotal + fulfillment_bonus - penalty)


# ---------------------------------------------------------------------------
# honey_revenue (PRD §3.7)
# ---------------------------------------------------------------------------
def honey_revenue(final_yield_kg, price_per_kg_cents):
    """(1) gross = round_half_up(final_yield_kg * price); (2) pick discount tier
    from gross; (3) net = gross - round_half_up(gross * discount_pct)."""
    gross = round_cents(D(final_yield_kg) * D(price_per_kg_cents))
    if gross >= TIER2_MIN:
        discount_pct = TIER2_DISCOUNT
    elif gross >= TIER1_MIN:
        discount_pct = TIER1_DISCOUNT
    else:
        discount_pct = Decimal("0")
    discount = round_cents(D(gross) * discount_pct)
    net = gross - discount
    return gross, net
