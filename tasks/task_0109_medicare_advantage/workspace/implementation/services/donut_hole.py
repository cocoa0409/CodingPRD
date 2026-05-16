"""Four-phase donut-hole drug cost calculation."""
from utils import round_half_up_cents

INITIAL_COVERAGE_COPAY_RATES = {
    "TIER_1": 0.05,
    "TIER_2": 0.15,
    "TIER_3": 0.25,
    "TIER_4": 0.40,
    "TIER_5": 0.50,
}
GAP_RATE = 0.25
CATASTROPHIC_RATE = 0.05

PHASES = ("DEDUCTIBLE", "INITIAL_COVERAGE", "COVERAGE_GAP", "CATASTROPHIC")


def _next_phase(ded_paid: int, spend: int, troop: int, D: int, I: int, C: int) -> str:
    """Phase the NEXT byte of spend (if any further) would enter, using updated counters."""
    if ded_paid < D:
        return "DEDUCTIBLE"
    if spend < I:
        return "INITIAL_COVERAGE"
    if troop < C:
        return "COVERAGE_GAP"
    return "CATASTROPHIC"


def phase_walk(
    *,
    gross_cost_cents: int,
    tier: str,
    plan: dict,
    pre_ded_paid: int,
    pre_spend: int,
    pre_troop: int,
) -> dict:
    """Run the four-phase walk and return per-phase deltas + claim totals + ending phase.

    Returns a dict with:
        beneficiary_cost_cents (int)
        plan_cost_cents (int)
        phase_at_adjudication (str)  -- last phase any byte touched
        delta_deductible_paid_cents
        delta_total_drug_spend_cents
        delta_troop_cents
        next_phase  -- phase the next byte would enter, using updated counters
    """
    D = int(plan.get("annual_deductible_cents", 0) or 0)
    I = int(plan.get("initial_coverage_limit_cents", 0) or 0)
    C = int(plan.get("catastrophic_threshold_cents", 0) or 0)

    ded_paid = int(pre_ded_paid)
    spend = int(pre_spend)
    troop = int(pre_troop)

    g = int(gross_cost_cents)
    bene_total = 0
    plan_total = 0
    last_phase_touched = None

    copay = INITIAL_COVERAGE_COPAY_RATES.get(tier, 0.0)

    # Phase 1: Deductible
    cover = min(g, max(0, D - ded_paid))
    if cover > 0:
        bene_total += cover
        ded_paid += cover
        spend += cover
        troop += cover
        g -= cover
        last_phase_touched = "DEDUCTIBLE"

    # Phase 2: Initial Coverage
    if g > 0:
        cover = min(g, max(0, I - spend))
        if cover > 0:
            bene_share = round_half_up_cents(cover * copay)
            plan_share = cover - bene_share
            bene_total += bene_share
            plan_total += plan_share
            spend += cover
            troop += bene_share
            g -= cover
            last_phase_touched = "INITIAL_COVERAGE"

    # Phase 3: Coverage Gap
    if g > 0:
        # Determine how much can be covered in the gap before TrOOP reaches the catastrophic threshold.
        # In the gap, only the beneficiary_share (25% of cover) is added to TrOOP.
        # We want: troop + round_half_up(cover * 0.25) < C, but per the formula in §3.8 the
        # phase ends when troop >= C. To keep this deterministic we proceed greedily over the
        # remaining gross within this phase: process the entire remaining gross at the gap
        # rate, but cap so that troop does not overshoot C in expectation (using the
        # un-rounded relationship). The PRD says "this phase ends — and Phase 4 begins —
        # when troop reaches or exceeds C", so we compute the integer cover such that the
        # rounded bene_share + troop just reaches or first exceeds C.
        # Strategy: do a single contiguous block until troop reaches C (or until g is
        # exhausted), then if more g remains, drop into catastrophic.
        remaining = g
        if troop < C:
            # Maximum cover within the gap so that bene_share <= (C - troop) — i.e. troop stays
            # strictly below C until the closing byte. Compute cover where rounded
            # round_half_up(cover * 0.25) just reaches (C - troop).
            shortfall = C - troop
            # We want the smallest cover where round_half_up(cover * 0.25) >= shortfall, but
            # cover is at most `remaining`. The upper-bound cover that pushes troop to (or
            # beyond) C is found by solving cover * 0.25 >= shortfall - 0.5 (because rounding
            # half-up means cover*0.25 + 0.5 >= shortfall ↔ cover >= 4*shortfall - 2). To
            # avoid floating issues we step ceiling: cover_to_cap = ceil((shortfall - 0.5) * 4)
            # but clamp to >=0 and to remaining.
            # Simpler & exact: use Decimal-free integer math with the rule
            #   round_half_up(cover * 0.25) >= shortfall
            #   <=> 2*cover + 2 >= 8*shortfall   (since cover*0.25 + 0.5 >= shortfall)
            #   <=> cover >= 4*shortfall - 2
            # But this is approximate. Instead we use a closed-form integer ceiling on
            # the unrounded value: smallest cover where cover/4 (rounded half-up) >= shortfall.
            # Concretely: cover_min = max(0, 4*shortfall - 2) — but to be safe we compute by
            # binary search on cover within [0, remaining].
            lo, hi = 0, remaining
            cover_to_cap = remaining  # if even the full remaining doesn't reach C, use it all
            while lo <= hi:
                mid = (lo + hi) // 2
                if round_half_up_cents(mid * GAP_RATE) >= shortfall:
                    cover_to_cap = mid
                    hi = mid - 1
                else:
                    lo = mid + 1
            cover = min(remaining, cover_to_cap)
            if cover > 0:
                bene_share = round_half_up_cents(cover * GAP_RATE)
                plan_share = cover - bene_share
                bene_total += bene_share
                plan_total += plan_share
                spend += cover
                troop += bene_share
                g -= cover
                last_phase_touched = "COVERAGE_GAP"

    # Phase 4: Catastrophic
    if g > 0:
        bene_share = round_half_up_cents(g * CATASTROPHIC_RATE)
        plan_share = g - bene_share
        bene_total += bene_share
        plan_total += plan_share
        spend += g
        troop += bene_share
        last_phase_touched = "CATASTROPHIC"
        g = 0

    if last_phase_touched is None:
        # No bytes consumed (e.g., gross_cost_cents was zero — but our caller enforces >=1).
        last_phase_touched = _next_phase(ded_paid, spend, troop, D, I, C)

    delta_ded = ded_paid - int(pre_ded_paid)
    delta_spend = spend - int(pre_spend)
    delta_troop = troop - int(pre_troop)

    return {
        "beneficiary_cost_cents": bene_total,
        "plan_cost_cents": plan_total,
        "phase_at_adjudication": last_phase_touched,
        "delta_deductible_paid_cents": delta_ded,
        "delta_total_drug_spend_cents": delta_spend,
        "delta_troop_cents": delta_troop,
        "next_phase": _next_phase(ded_paid, spend, troop, D, I, C),
        "post_ded_paid": ded_paid,
        "post_spend": spend,
        "post_troop": troop,
    }


def replay_chronological(claims_in_order, plan: dict) -> dict:
    """Replay a list of claims (each with gross_cost_cents and tier) chronologically
    against an empty starting ledger. Returns final counters and per-claim outputs.
    """
    ded_paid = 0
    spend = 0
    troop = 0
    per_claim = []
    for c in claims_in_order:
        result = phase_walk(
            gross_cost_cents=c["gross_cost_cents"],
            tier=c["tier"],
            plan=plan,
            pre_ded_paid=ded_paid,
            pre_spend=spend,
            pre_troop=troop,
        )
        ded_paid = result["post_ded_paid"]
        spend = result["post_spend"]
        troop = result["post_troop"]
        per_claim.append(result)
    return {
        "ded_paid": ded_paid,
        "spend": spend,
        "troop": troop,
        "per_claim": per_claim,
    }
