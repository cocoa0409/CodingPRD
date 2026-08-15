"""Calculation rules (scaffold 1.3): discount matrix, bid scoring, line commitment,
invoice reimbursement — implemented exactly with Decimal / integer-half-up rounding."""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.core import (
    touch, c2_cap_cents, c2_committed_cents, invoice_deadline_for_cycle,
    lines_of_request,
)
from util import quantize_2dp, round_half_up_int

# ---------------------------------------------------------------------------
# discount_rate_lookup (PRD 3.2)
# ---------------------------------------------------------------------------

# Band lower edges: [0,1) [1,20) [20,35) [35,50) [50,75) [75,100] (top closed).
MATRIX = {
    ("CATEGORY_ONE", "URBAN"): [20, 40, 50, 60, 80, 90],
    ("CATEGORY_ONE", "RURAL"): [25, 50, 60, 70, 80, 90],
    ("CATEGORY_TWO", "URBAN"): [20, 40, 50, 60, 80, 85],
    ("CATEGORY_TWO", "RURAL"): [25, 50, 60, 70, 80, 85],
}

CEP_MULTIPLIER = Decimal("1.6")
CEP_SHARE_CAP = Decimal("100.00")


def band_index(share) -> int:
    """First band with BAND_LO <= share < BAND_HI; last band includes 100.
    share exactly equal to a lower bound enters that band."""
    s = Decimal(str(share))
    if s < 1:
        return 0
    if s < 20:
        return 1
    if s < 35:
        return 2
    if s < 50:
        return 3
    if s < 75:
        return 4
    return 5


def discount_rate(category: str, urban_rural: str, share) -> int:
    return MATRIX[(category, urban_rural)][band_index(share)]


def compute_effective_share(total_students, free_lunch_eligible, cep_participating,
                            cep_identified_student_pct) -> float:
    """2-decimal percentage, round half up.
    DIRECT_SNAPSHOT: round_half_up(100 * free / total, 2).
    CEP_PROJECTED:   min(cep_identified_student_pct * 1.6, 100.00)."""
    if cep_participating:
        val = Decimal(repr(cep_identified_student_pct)) * CEP_MULTIPLIER
        if val > CEP_SHARE_CAP:
            val = CEP_SHARE_CAP
        return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    val = Decimal(100 * free_lunch_eligible) / Decimal(total_students)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# winning_bid_score (PRD 3.3)
# ---------------------------------------------------------------------------

def score_qualified_bids(posting, candidates):
    """Compute total_score (2dp, half-up per component and for the total) for
    every QUALIFIED candidate; returns {bid_id: Decimal total}."""
    lowest_price = min(b["eligible_price_cents"] for b in candidates)
    price_weight = posting["price_weight_pct"]
    weights = posting["other_factor_weights"]
    totals = {}
    for b in candidates:
        price_points = quantize_2dp(
            Decimal(lowest_price) * Decimal(price_weight)
            / Decimal(b["eligible_price_cents"])
        )
        score_map = {fs["factor_name"]: fs["score"] for fs in b["factor_scores"]}
        factor_points = Decimal(0)
        for w in weights:
            # each term exact to 2dp (integer weight * integer score / 100)
            factor_points += (
                Decimal(w["weight_pct"] * score_map[w["factor_name"]]) / Decimal(100)
            )
        totals[b["id"]] = quantize_2dp(price_points + factor_points)
    return totals


def pick_winner(candidates, totals):
    """Highest total_score; tie -> lower eligible_price_cents; tie -> earlier
    created_at (sequential creation => _seq ordering)."""
    return min(
        candidates,
        key=lambda b: (-totals[b["id"]], b["eligible_price_cents"], b["_seq"]),
    )


# ---------------------------------------------------------------------------
# frn_line_commitment + c2_budget_allocation_order (PRD 3.5, 3.8)
# ---------------------------------------------------------------------------

def run_line_commitment(request, lines):
    """Walk lines in created_at ASC order. CATEGORY_TWO lines draw from the C2
    budget waterfall (allocation = min(requested, remaining at turn), decrement
    before the next line's turn; zero allocation -> DENIED/INSUFFICIENT_BUDGET).
    CATEGORY_ONE lines are uncapped (committed_pre = requested, no budget draw).
    committed_share_cents = round_half_up(committed_pre * pinned rate / 100),
    computed per line, never on aggregates. Mutates lines; recomputes the
    request total (caller's touch covers the request-level write)."""
    applicant = db["applicants"][request["applicant_id"]]
    cycle = db["funding_cycles"][request["funding_cycle_id"]]
    deadline = invoice_deadline_for_cycle(cycle)
    remaining = c2_cap_cents(applicant) - c2_committed_cents(request["applicant_id"])
    for line in sorted(lines, key=lambda l: l["_seq"]):
        if line["category"] == "CATEGORY_ONE":
            allocation = line["requested_pre_discount_cents"]
            rate = request["discount_rate_c1_pct"]
        else:
            allocation = min(line["requested_pre_discount_cents"], remaining)
            rate = request["discount_rate_c2_pct"]
            remaining -= allocation  # decrement before the next line's turn
        if allocation <= 0:
            line["status"] = "DENIED"
            line["denial_reason"] = "INSUFFICIENT_BUDGET"
            touch(line)
            continue
        share = round_half_up_int(allocation * rate, 100)
        line["committed_pre_discount_cents"] = allocation
        line["committed_share_cents"] = share
        line["remaining_reimbursable_cents"] = share
        line["invoice_deadline_date"] = deadline
        line["denial_reason"] = None
        line["status"] = "COMMITTED"
        touch(line)
    request["committed_total_share_cents"] = sum(
        l["committed_share_cents"]
        for l in lines_of_request(request["id"])
        if l["status"] == "COMMITTED"
    )


# ---------------------------------------------------------------------------
# invoice_reimbursement (PRD 3.6)
# ---------------------------------------------------------------------------

def tentative_reimbursement(invoice, line, request) -> int:
    """rate = pinned discount rate on the line's request for the line's category.
    BEAR: base = min(applicant_paid_cents, gross_invoiced_cents).
    SPI:  base = gross_invoiced_cents.
    tentative = round_half_up(base * rate / 100) to integer cents."""
    if line["category"] == "CATEGORY_ONE":
        rate = request["discount_rate_c1_pct"]
    else:
        rate = request["discount_rate_c2_pct"]
    if invoice["method"] == "BEAR":
        base = min(invoice["applicant_paid_cents"], invoice["gross_invoiced_cents"])
    else:  # SPI
        base = invoice["gross_invoiced_cents"]
    return round_half_up_int(base * rate, 100)
