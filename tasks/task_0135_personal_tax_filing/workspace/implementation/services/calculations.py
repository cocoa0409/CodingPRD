"""Tax computation pipeline (PRD §3.5, §3.6, §3.7, §3.10).

All amounts are integer cents. The PRD pins evaluation order at every
step and specifies truncation toward zero (floor for non-negative)
on every integer ratio. Safe-harbor thresholds use ceiling.
"""
from __future__ import annotations

from utils import ceil_div


# ── Schedule aggregate refresh (§3.3) ────────────────────────────────────


def refresh_schedule_aggregates(return_obj: dict, income_docs: list, schedules: list) -> None:
    """Refresh computed Schedule.* fields from the return's children.

    Mutates the schedule dicts in place (caller is expected to bump
    each modified schedule's updated_at/version separately if needed).
    """
    # Schedule B aggregates from income docs.
    sum_int = sum(
        d.get("interest_income_cents", 0) or 0
        for d in income_docs
        if d["doc_type"] == "1099_INT"
    )
    sum_div = sum(
        d.get("ordinary_dividends_cents", 0) or 0
        for d in income_docs
        if d["doc_type"] == "1099_DIV"
    )

    # Schedule D buckets from 1099-B docs.
    short_gain = 0
    long_gain = 0
    for d in income_docs:
        if d["doc_type"] != "1099_B":
            continue
        hp = d.get("holding_period", "NONE")
        gain = (d.get("proceeds_cents", 0) or 0) - (d.get("cost_basis_cents", 0) or 0)
        if hp == "SHORT_TERM":
            short_gain += gain
        elif hp == "LONG_TERM":
            long_gain += gain

    for s in schedules:
        if s["schedule_type"] == "B":
            s["schedule_b_interest_cents"] = sum_int
            s["schedule_b_dividends_cents"] = sum_div
        if s["schedule_type"] == "D":
            s["schedule_d_short_term_gain_cents"] = short_gain
            s["schedule_d_long_term_gain_cents"] = long_gain


# ── calc_agi (§3.5 Step 1) ───────────────────────────────────────────────


def calc_agi(return_obj: dict, income_docs: list, schedules: list) -> tuple[int, int, int]:
    """Compute (total_income_cents, agi_cents, schedule_c_net_cents).

    schedule_c_net_cents is needed by SE-tax adjustment math and is
    returned alongside so the caller can stash it.
    """
    total_wages = sum(d.get("wages_cents", 0) or 0 for d in income_docs if d["doc_type"] == "W2")
    total_nec = sum(d.get("nonemployee_comp_cents", 0) or 0 for d in income_docs if d["doc_type"] == "1099_NEC")
    total_int = sum(d.get("interest_income_cents", 0) or 0 for d in income_docs if d["doc_type"] == "1099_INT")
    total_div = sum(d.get("ordinary_dividends_cents", 0) or 0 for d in income_docs if d["doc_type"] == "1099_DIV")

    # Schedule C: sum of (gross - expenses) across all C schedules, floored at 0.
    sched_c_raw = 0
    for s in schedules:
        if s["schedule_type"] == "C":
            sched_c_raw += (s.get("schedule_c_gross_receipts_cents", 0) or 0) - (
                s.get("schedule_c_expenses_cents", 0) or 0
            )
    schedule_c_net = max(0, sched_c_raw)

    # Schedule E: sum of (rental_income - rental_expenses), floored at 0.
    sched_e_raw = 0
    for s in schedules:
        if s["schedule_type"] == "E":
            sched_e_raw += (s.get("schedule_e_rental_income_cents", 0) or 0) - (
                s.get("schedule_e_rental_expenses_cents", 0) or 0
            )
    schedule_e_net = max(0, sched_e_raw)

    # Capital gains: PRD §3.3 — "Schedule D's two computed fields ... are
    # populated from the 1099_B documents attached to the return."
    # PRD §3.5 Step 1 — "the combined Schedule D capital-gains net
    # (short-term gain plus long-term gain), with the capital-gains
    # contribution floored at negative 300,000 cents".
    # The capital-gains contribution is therefore derived from the
    # 1099_B income documents themselves; the Schedule D row (if any)
    # only mirrors the same computation for reporting purposes.
    cg_short = 0
    cg_long = 0
    for d in income_docs:
        if d["doc_type"] != "1099_B":
            continue
        hp = d.get("holding_period", "NONE")
        gain = (d.get("proceeds_cents", 0) or 0) - (d.get("cost_basis_cents", 0) or 0)
        if hp == "SHORT_TERM":
            cg_short += gain
        elif hp == "LONG_TERM":
            cg_long += gain
    cap_gains_net = max(cg_short + cg_long, -300000)

    total_income = (
        total_wages
        + total_nec
        + total_int
        + total_div
        + schedule_c_net
        + schedule_e_net
        + cap_gains_net
    )

    # Half-SE adjustment: floor(SE * 0.9235 * 0.153) / 2 with truncation per step.
    # Two integer ratio steps as specified in the SCAFFOLD formula.
    se_net = (schedule_c_net * 9235) // 10000  # 0.9235 of net
    se_tax = (se_net * 1530) // 10000  # 15.30%
    half_se = se_tax // 2

    agi = total_income - half_se

    return total_income, agi, schedule_c_net


# ── calc_taxable_income (§3.5 Step 2) ────────────────────────────────────

STD_DEDUCTION_TABLE = {
    "SINGLE": 1_500_000,
    "MARRIED_SEPARATE": 1_500_000,
    "MARRIED_JOINT": 3_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 3_000_000,
    "HEAD_OF_HOUSEHOLD": 2_225_000,
}

BLIND_ADDON_CENTS = 150_000


def calc_taxable_income(
    return_obj: dict,
    taxpayer_obj: dict,
    schedules: list,
    agi_cents: int,
) -> tuple[int, int]:
    """Return (taxable_income_cents, total_itemized_deduction_cents_or_0).

    The second value is the itemized total used when method=ITEMIZED,
    so the caller can write it back to the Schedule A row. When the
    return is on the standard path it's 0.
    """
    filing_status = return_obj["filing_status"]
    deduction_method = return_obj["deduction_method"]
    is_blind = bool(taxpayer_obj.get("is_blind", False))

    if deduction_method == "STANDARD":
        deduction = STD_DEDUCTION_TABLE[filing_status] + (BLIND_ADDON_CENTS if is_blind else 0)
        itemized_total = 0
    else:  # ITEMIZED
        # Find Schedule A.
        sched_a = next((s for s in schedules if s["schedule_type"] == "A"), None)
        if sched_a is None:
            # No Schedule A attached: itemized deduction is zero.
            deduction = 0
            itemized_total = 0
        else:
            # Pin order from PRD §3.5 Step 2: medical floor → SALT cap →
            # mortgage (no cap) → charity cap → sum.
            medical_floor = (agi_cents * 750) // 10000  # 7.5% of AGI
            medical_allowed = max(0, (sched_a.get("itemized_medical_cents", 0) or 0) - medical_floor)
            salt_allowed = min(sched_a.get("itemized_salt_cents", 0) or 0, 1_000_000)
            mortgage_allowed = sched_a.get("itemized_mortgage_interest_cents", 0) or 0
            charity_cap = (agi_cents * 60) // 100  # 60% AGI cap, floor
            charity_allowed = min(sched_a.get("itemized_charity_cents", 0) or 0, charity_cap)
            deduction = medical_allowed + salt_allowed + mortgage_allowed + charity_allowed
            itemized_total = deduction

    taxable = max(0, agi_cents - deduction)
    return taxable, itemized_total


# ── calc_regular_tax (§3.5 Step 3) ───────────────────────────────────────

# Brackets defined as list of (lo, hi, bps) with hi=None meaning infinity.
BRACKETS_SINGLE = [
    (0, 1_100_000, 1000),
    (1_100_000, 4_475_000, 1200),
    (4_475_000, 9_537_500, 2200),
    (9_537_500, 18_222_500, 2400),
    (18_222_500, None, 3200),
]

BRACKETS_MARRIED_JOINT = [
    (0, 2_200_000, 1000),
    (2_200_000, 8_950_000, 1200),
    (8_950_000, 19_075_000, 2200),
    (19_075_000, None, 2400),
]


def _brackets_for(filing_status: str):
    if filing_status in ("MARRIED_JOINT", "QUALIFYING_SURVIVING_SPOUSE"):
        return BRACKETS_MARRIED_JOINT
    # SINGLE, MARRIED_SEPARATE, HEAD_OF_HOUSEHOLD use single-style table
    # per the simplified PRD model.
    return BRACKETS_SINGLE


def calc_regular_tax(taxable_income_cents: int, filing_status: str) -> int:
    """Sum per-bracket slice taxes; floor each slice before summing."""
    brackets = _brackets_for(filing_status)
    tax = 0
    for lo, hi, bps in brackets:
        if taxable_income_cents <= lo:
            break
        slice_top = taxable_income_cents if hi is None else min(taxable_income_cents, hi)
        slice_amt = slice_top - lo
        if slice_amt <= 0:
            break
        tax += (slice_amt * bps) // 10000  # floor each bracket slice
    return tax


# ── calc_amt (§3.5 Step 4) ───────────────────────────────────────────────

AMT_EXEMPTION = {
    "SINGLE": 8_550_000,
    "HEAD_OF_HOUSEHOLD": 8_550_000,
    "MARRIED_JOINT": 13_325_000,
    "QUALIFYING_SURVIVING_SPOUSE": 13_325_000,
    "MARRIED_SEPARATE": 6_662_500,
}

AMT_BRACKET_BREAK_CENTS = 23_222_500


def calc_amt(agi_cents: int, filing_status: str, regular_tax_cents: int) -> int:
    """Return amt_cents (>= 0). Final tax used downstream is regular + amt."""
    amti = agi_cents  # simplified: no preference adjustments
    exemption = AMT_EXEMPTION[filing_status]
    amt_base = max(0, amti - exemption)
    if amt_base <= AMT_BRACKET_BREAK_CENTS:
        tentative = (amt_base * 2600) // 10000
    else:
        low = (AMT_BRACKET_BREAK_CENTS * 2600) // 10000
        high = ((amt_base - AMT_BRACKET_BREAK_CENTS) * 2800) // 10000
        tentative = low + high
    return max(0, tentative - regular_tax_cents)


# ── calc_credits (§3.6) ──────────────────────────────────────────────────

CTC_BASE_PER_CHILD = 200_000
CTC_REFUNDABLE_CAP_PER_CHILD = 170_000
CTC_PHASEOUT_START = {
    "SINGLE": 20_000_000,
    "MARRIED_SEPARATE": 20_000_000,
    "HEAD_OF_HOUSEHOLD": 20_000_000,
    "MARRIED_JOINT": 40_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 40_000_000,
}
CTC_PHASEOUT_RATE_BPS = 500

AOTC_PHASEOUT_START = {
    "SINGLE": 8_000_000,
    "HEAD_OF_HOUSEHOLD": 8_000_000,
    "MARRIED_JOINT": 16_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 16_000_000,
    "MARRIED_SEPARATE": 0,
}
AOTC_PHASEOUT_RANGE = {
    "SINGLE": 1_000_000,
    "HEAD_OF_HOUSEHOLD": 1_000_000,
    "MARRIED_JOINT": 2_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 2_000_000,
    "MARRIED_SEPARATE": 0,
}

EITC_MAX = {0: 60_000, 1: 400_000, 2: 660_000, 3: 740_000}
EITC_PHASEOUT_START = {0: 1_000_000, 1: 2_200_000, 2: 2_200_000, 3: 2_200_000}
EITC_PHASEOUT_END = {0: 1_882_000, 1: 4_949_000, 2: 5_535_000, 3: 5_907_000}


def _compute_ctc(agi_cents: int, filing_status: str, qualifying_children: int) -> tuple[int, int, int, str | None]:
    """Return (total, refundable, nonrefundable, ineligibility_reason)."""
    if qualifying_children <= 0:
        return 0, 0, 0, "No qualifying children under 17"
    gross = qualifying_children * CTC_BASE_PER_CHILD
    excess = max(0, agi_cents - CTC_PHASEOUT_START[filing_status])
    # Round excess UP to next $1000 step: add 99999 and trunc by 100000.
    excess_rounded = ((excess + 99_999) // 100_000) * 100_000
    phaseout = (excess_rounded * CTC_PHASEOUT_RATE_BPS) // 10000
    total = max(0, gross - phaseout)
    refundable = min(total, qualifying_children * CTC_REFUNDABLE_CAP_PER_CHILD)
    nonrefundable = total - refundable
    return total, refundable, nonrefundable, None


def _compute_aotc(
    agi_cents: int,
    filing_status: str,
    aotc_student_count: int,
    aotc_qualified_expenses_cents: int,
) -> tuple[int, int, int, str | None]:
    if filing_status == "MARRIED_SEPARATE":
        return 0, 0, 0, "AOTC unavailable for MARRIED_SEPARATE"
    if aotc_student_count <= 0:
        return 0, 0, 0, "AOTC requires at least one student"
    if aotc_qualified_expenses_cents <= 0:
        return 0, 0, 0, "AOTC requires positive qualified expenses"

    # Per-student qualified expenses, capped at 400,000 cents.
    per_student = aotc_qualified_expenses_cents // aotc_student_count
    per_student = min(per_student, 400_000)

    if per_student <= 200_000:
        raw_per_student = per_student
    else:
        # 100% of first $2000 + 25% of portion above $2000.
        excess_over_2000 = per_student - 200_000
        raw_per_student = 200_000 + (excess_over_2000 * 2500) // 10000

    aotc_gross = aotc_student_count * raw_per_student

    # Phase-out.
    phaseout_range = AOTC_PHASEOUT_RANGE[filing_status]
    if phaseout_range == 0:
        return 0, 0, 0, "AOTC ineligible at this filing status"
    excess = max(0, agi_cents - AOTC_PHASEOUT_START[filing_status])
    if excess >= phaseout_range:
        return 0, 0, 0, "AOTC fully phased out"
    retain_bps = 10000 - (excess * 10000) // phaseout_range
    aotc_total = (aotc_gross * retain_bps) // 10000
    aotc_refundable = (aotc_total * 40) // 100
    aotc_nonrefundable = aotc_total - aotc_refundable
    return aotc_total, aotc_refundable, aotc_nonrefundable, None


def _compute_eitc(
    agi_cents: int, filing_status: str, qualifying_children: int
) -> tuple[int, int, str | None]:
    """Returns (total, refundable=total, reason_if_zero)."""
    if filing_status == "MARRIED_SEPARATE":
        return 0, 0, "EITC unavailable for MARRIED_SEPARATE"
    kids = min(max(0, qualifying_children), 3)
    max_credit = EITC_MAX[kids]
    start = EITC_PHASEOUT_START[kids]
    end = EITC_PHASEOUT_END[kids]
    if agi_cents <= start:
        total = max_credit
    elif agi_cents >= end:
        return 0, 0, "EITC fully phased out (AGI above limit)"
    else:
        range_ = end - start
        retained_bps = 10000 - ((agi_cents - start) * 10000) // range_
        total = (max_credit * retained_bps) // 10000
    return total, total, None


def compute_credits(
    return_obj: dict,
    credits: list,
    agi_cents: int,
    regular_tax_cents: int,
    amt_cents: int,
) -> tuple[int, int, int]:
    """Apply per-credit phase-out/cap, refundable/non-refundable split, and
    the pool waterfall.

    Mutates each TaxCredit row in `credits` in place to set:
      eligibility_status, approved_amount_cents, refundable_portion_cents,
      ineligibility_reason

    Returns (total_credits_cents, applied_nonref_cents, applied_refundable_cents).

    `applied_nonref_cents` is the non-refundable pool clamped at final_tax;
    `applied_refundable_cents` is the full refundable pool. The caller can
    use these to compute net_tax = final_tax - applied_nonref - applied_refundable.
    """
    final_tax = regular_tax_cents + amt_cents
    filing_status = return_obj["filing_status"]
    qualifying_children = return_obj.get("qualifying_children_under_17", 0) or 0

    nonref_pool = 0
    refundable_pool = 0
    total_approved = 0

    # Compute each credit's per-row totals.
    for credit in credits:
        ctype = credit["credit_type"]
        if ctype == "CTC":
            total, refundable, nonrefundable, reason = _compute_ctc(
                agi_cents, filing_status, qualifying_children
            )
        elif ctype == "AOTC":
            total, refundable, nonrefundable, reason = _compute_aotc(
                agi_cents,
                filing_status,
                credit.get("aotc_student_count", 0) or 0,
                credit.get("aotc_qualified_expenses_cents", 0) or 0,
            )
        elif ctype == "EITC":
            total, refundable, reason = _compute_eitc(
                agi_cents, filing_status, qualifying_children
            )
            nonrefundable = 0  # EITC fully refundable
        else:
            total, refundable, nonrefundable, reason = 0, 0, 0, "Unknown credit type"

        if reason is not None:
            credit["eligibility_status"] = "INELIGIBLE"
            credit["approved_amount_cents"] = 0
            credit["refundable_portion_cents"] = 0
            credit["ineligibility_reason"] = reason
        else:
            credit["eligibility_status"] = "ELIGIBLE"
            credit["approved_amount_cents"] = total
            credit["refundable_portion_cents"] = refundable
            credit["ineligibility_reason"] = None
            nonref_pool += nonrefundable
            refundable_pool += refundable
            total_approved += total

    applied_nonref = min(nonref_pool, final_tax)
    return total_approved, applied_nonref, refundable_pool


# ── calc_balance_due_or_refund (§3.7) ────────────────────────────────────


def calc_balance(
    regular_tax_cents: int,
    amt_cents: int,
    applied_nonref_cents: int,
    refundable_pool_cents: int,
    total_withholding_cents: int,
    estimated_payments_applied_cents: int,
) -> tuple[int, int]:
    """Return (balance_due_or_refund_cents, net_tax_cents).

    Per PRD §3.7: net_tax = (final_tax - applied_nonref) - refundable_pool
    (may be negative). balance = payments - net_tax (positive => refund).
    """
    final_tax = regular_tax_cents + amt_cents
    remaining_tax = final_tax - applied_nonref_cents
    net_tax = remaining_tax - refundable_pool_cents
    payments = total_withholding_cents + estimated_payments_applied_cents
    balance = payments - net_tax
    return balance, net_tax


# ── Safe-harbor (§3.10) ──────────────────────────────────────────────────


def calc_safe_harbor(
    current_tax_cents: int,
    agi_cents: int,
    payments_made_cents: int,
    prior_total_tax_cents: int | None,
) -> dict:
    """Return the dict the safe-harbor endpoint exposes."""
    threshold_current = ceil_div(current_tax_cents * 90, 100)
    if prior_total_tax_cents is None:
        prior_threshold = None
        prior_threshold_for_check = None
    else:
        if agi_cents > 15_000_000:
            prior_threshold = ceil_div(prior_total_tax_cents * 110, 100)
        else:
            prior_threshold = ceil_div(prior_total_tax_cents * 100, 100)
        prior_threshold_for_check = prior_threshold

    safe_harbor_met = payments_made_cents >= threshold_current
    if not safe_harbor_met and prior_threshold_for_check is not None:
        safe_harbor_met = payments_made_cents >= prior_threshold_for_check

    return {
        "current_tax_cents": current_tax_cents,
        "payments_made_cents": payments_made_cents,
        "threshold_current_cents": threshold_current,
        "prior_threshold_cents": prior_threshold,
        "safe_harbor_met": safe_harbor_met,
    }
