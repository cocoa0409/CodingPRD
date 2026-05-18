"""Pure calculation rules — see SCAFFOLD §1.3 and PRD §3.

These functions are deterministic given their inputs; they never read the
store directly. Integer cents are used throughout; Decimal is used as an
intermediate for any rounding-sensitive arithmetic. The round-half-up
contract is honoured at every cent boundary.
"""
from __future__ import annotations

from decimal import Decimal

from config import (
    BASE_BPS_TABLE,
    FINAL_CASHFLOW_CEILING_CENTS,
    FINAL_NSF_PENALTY_CEILING,
    FINAL_NSF_PENALTY_PER_EVENT,
    FINAL_RESERVES_CEILING_CENTS,
    GRADE_BANDS,
    PROV_REQUEST_CEILING_CENTS,
    PROV_REQUEST_FLOOR_CENTS,
    PROV_REVENUE_CEILING_CENTS,
    PROV_REVENUE_FLOOR_CENTS,
    TERM_PREMIUM_BPS_PER_MONTH_OVER_24,
)
from utils import clamp, round_half_up_to_4dp, round_half_up_to_int


# ── Borrower scoring ───────────────────────────────────────────────────────


def _band_from_score(score: Decimal) -> str:
    for threshold, letter in GRADE_BANDS:
        if score >= Decimal(str(threshold)):
            return letter
    return "E"


def _normalize_linear(value: int, lo: int, hi: int) -> Decimal:
    """Linear normalize to [0,1] with clamping. value is integer cents."""
    if value <= lo:
        return Decimal("0")
    if value >= hi:
        return Decimal("1")
    return (Decimal(value) - Decimal(lo)) / (Decimal(hi) - Decimal(lo))


def compute_provisional_grade(annual_revenue_cents: int, requested_amount_cents: int) -> str:
    """SCAFFOLD calc: borrower_provisional_grade.

    score_self = 0.6 * normalize(revenue) + 0.4 * (1 - normalize(requested))
    Rounded half-up to 4 decimals before banding.
    """
    rev_norm = _normalize_linear(
        annual_revenue_cents, PROV_REVENUE_FLOOR_CENTS, PROV_REVENUE_CEILING_CENTS
    )
    req_norm = _normalize_linear(
        requested_amount_cents, PROV_REQUEST_FLOOR_CENTS, PROV_REQUEST_CEILING_CENTS
    )
    score = Decimal("0.6") * rev_norm + Decimal("0.4") * (Decimal("1") - req_norm)
    score = round_half_up_to_4dp(score)
    return _band_from_score(score)


def compute_final_grade(borrower: dict, snapshot: dict | None) -> str:
    """SCAFFOLD calc: borrower_final_grade.

    Uses the borrower's LATEST PlaidSnapshot. Without a snapshot, final_grade
    is UNGRADED. The DTI numerator uses the snapshot's existing_debt_service
    annualized; the denominator uses the borrower's self-reported revenue
    (this is the deliberate dual-variant divergence point — see PRD §3.2).
    """
    if snapshot is None:
        return "UNGRADED"

    deposits = snapshot["deposits_last_90d_cents"]
    avg_bal = snapshot["avg_daily_balance_cents"]
    nsf_count = snapshot["nsf_count_last_90d"]
    debt_service = snapshot["existing_debt_service_cents"]
    annual_revenue = max(borrower.get("annual_revenue_cents") or 0, 1)

    # Cashflow component: deposits / 90, clamped to [0, ceiling].
    cashflow = Decimal(deposits) / Decimal(90)
    cashflow = clamp(cashflow, Decimal(0), Decimal(FINAL_CASHFLOW_CEILING_CENTS))
    cashflow_norm = cashflow / Decimal(FINAL_CASHFLOW_CEILING_CENTS)

    # Reserves component.
    reserves = clamp(Decimal(avg_bal), Decimal(0), Decimal(FINAL_RESERVES_CEILING_CENTS))
    reserves_norm = reserves / Decimal(FINAL_RESERVES_CEILING_CENTS)

    # NSF penalty: nsf_count * 0.10, clamped to [0, 0.50]; contribution is (1 - penalty).
    nsf_penalty = Decimal(nsf_count) * Decimal(str(FINAL_NSF_PENALTY_PER_EVENT))
    nsf_penalty = clamp(nsf_penalty, Decimal(0), Decimal(str(FINAL_NSF_PENALTY_CEILING)))
    nsf_contrib = Decimal(1) - nsf_penalty

    # DTI: (debt_service * 12) / max(annual_revenue, 1), clamped to [0,1]; contribution is (1 - dti).
    dti = (Decimal(debt_service) * Decimal(12)) / Decimal(annual_revenue)
    dti = clamp(dti, Decimal(0), Decimal(1))
    dti_contrib = Decimal(1) - dti

    score = (
        Decimal("0.35") * cashflow_norm
        + Decimal("0.30") * reserves_norm
        + Decimal("0.25") * dti_contrib
        + Decimal("0.10") * nsf_contrib
    )
    score = round_half_up_to_4dp(score)
    return _band_from_score(score)


# ── Listing pricing ────────────────────────────────────────────────────────


def compute_interest_rate_bps(grade: str, term_months: int) -> int:
    """SCAFFOLD calc: tiered_interest_rate."""
    base = BASE_BPS_TABLE[grade]
    premium = max(0, term_months - 24) * TERM_PREMIUM_BPS_PER_MONTH_OVER_24
    return base + premium


# ── Amortization ───────────────────────────────────────────────────────────


def compute_monthly_payment_cents(principal_cents: int, interest_rate_bps: int, term_months: int) -> int:
    """SCAFFOLD calc: monthly_amortized_payment, level payment.

    r = annual_rate / 12 = bps/10000/12
    monthly = P * r * (1+r)^n / ((1+r)^n - 1)  ; or P/n if r == 0.
    Rounded half-up to whole cents.
    """
    r = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(12)
    if r == 0:
        return round_half_up_to_int(Decimal(principal_cents) / Decimal(term_months))
    one_plus_r_n = (Decimal(1) + r) ** term_months
    numerator = Decimal(principal_cents) * r * one_plus_r_n
    denominator = one_plus_r_n - Decimal(1)
    return round_half_up_to_int(numerator / denominator)


def build_amortization_schedule(
    principal_cents: int, interest_rate_bps: int, term_months: int, monthly_payment_cents: int
):
    """Generate the per-installment scheduled principal / interest splits.

    The last installment absorbs rounding residual so that the sum of
    scheduled_principal_cents equals principal_cents exactly.
    """
    r = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(12)
    remaining = Decimal(principal_cents)
    schedule = []
    for k in range(1, term_months + 1):
        if r == 0:
            interest = 0
        else:
            interest = round_half_up_to_int(remaining * r)
        # principal portion = level monthly payment minus the interest portion,
        # but never larger than the remaining outstanding principal.
        principal_portion = monthly_payment_cents - interest
        if principal_portion < 0:
            principal_portion = 0
        if k == term_months:
            # Final installment absorbs residual.
            principal_portion = int(remaining)
        if principal_portion > int(remaining):
            principal_portion = int(remaining)
        schedule.append((principal_portion, interest))
        remaining -= Decimal(principal_portion)
    # Defensive: in case rounding has driven remaining slightly off, true-up the last item.
    total_principal = sum(p for p, _ in schedule)
    if total_principal != principal_cents and schedule:
        last_p, last_i = schedule[-1]
        delta = principal_cents - total_principal
        schedule[-1] = (last_p + delta, last_i)
    return schedule


# ── Investment diversification ────────────────────────────────────────────


def diversification_cap_cents(committed_capital_cents: int, max_borrower_concentration_bps: int) -> int:
    """SCAFFOLD calc: investor_diversification_check cap = floor(C * bps / 10000)."""
    return int(
        (Decimal(committed_capital_cents) * Decimal(max_borrower_concentration_bps))
        / Decimal(10000)
    )


# ── Origination fee ───────────────────────────────────────────────────────


def origination_fee_cents(principal_cents: int, origination_fee_bps: int) -> int:
    """floor(principal_cents * origination_fee_bps / 10000) — see PRD §3.4."""
    return int(
        (Decimal(principal_cents) * Decimal(origination_fee_bps)) / Decimal(10000)
    )


# ── Servicing fee ─────────────────────────────────────────────────────────


def servicing_fee_cents(scheduled_interest_due_cents: int, servicing_fee_bps: int) -> int:
    """Servicing fee on scheduled interest due — round_half_up to cents.

    Per PRD §3.5: "the floor of that scheduled interest due multiplied by
    servicing_fee_bps divided by 10000, rounded half-up to cents". The PRD
    couples floor + round_half_up, which is read as: compute the product,
    round_half_up to integer cents (the integer-cent floor is implicit
    since the scheduled interest is in cents).
    """
    if scheduled_interest_due_cents <= 0 or servicing_fee_bps <= 0:
        return 0
    return round_half_up_to_int(
        Decimal(scheduled_interest_due_cents) * Decimal(servicing_fee_bps) / Decimal(10000)
    )


# ── Share basis points at origination ─────────────────────────────────────


def share_bps(amount_cents: int, principal_cents: int) -> int:
    return round_half_up_to_int(
        Decimal(amount_cents) * Decimal(10000) / Decimal(principal_cents)
    )


# ── Charge-off loss distribution ──────────────────────────────────────────


def charge_off_loss_shares(total_loss_cents: int, investments_in_order):
    """Compute per-investment loss share with round-half-up and residual on last.

    investments_in_order: iterable of dicts with key 'share_bps' (and id, for
    output identification). The function returns a list of (investment, actual_share_cents)
    in the same order, ensuring the sum equals total_loss_cents exactly.
    """
    out = []
    remaining = total_loss_cents
    materialized = list(investments_in_order)
    n = len(materialized)
    for i, inv in enumerate(materialized):
        if i == n - 1:
            # Last investment absorbs residual.
            share = remaining
            if share < 0:
                share = 0
        else:
            gross = round_half_up_to_int(
                Decimal(total_loss_cents) * Decimal(inv.get("share_bps", 0)) / Decimal(10000)
            )
            share = min(gross, remaining)
        remaining -= share
        out.append((inv, share))
    return out


# ── Payment waterfall ─────────────────────────────────────────────────────


def waterfall_allocate(
    payment_amount_cents: int,
    installments: list,
    late_fee_cents_per_event: int,
    servicing_fee_bps: int,
):
    """Run the payment waterfall and return:
        allocation dict (fees, interest, principal, late_fees, unallocated)
        list of per-installment updates [(installment_id, delta_paid_principal,
            delta_paid_interest, delta_paid_fees)]

    Step order (pinned):
      1. Servicing fee on scheduled interest DUE on currently-DUE/LATE installments,
         deducted from the payment up-front (recorded as fees_cents).
      2. Late fees on currently-LATE installments (oldest first).
      3. Scheduled interest on overdue (LATE+DUE) installments oldest first.
      4. Scheduled principal on overdue installments oldest first.
      5. Prepayment principal on next upcoming installment (SCHEDULED).
      6. Any leftover → unallocated.

    `installments` is the full list for the loan (any status), sorted by
    sequence_number ascending. The caller is responsible for resorting if
    needed. The function does not mutate installments — it returns deltas.
    """
    remaining = payment_amount_cents
    fees_cents = 0
    late_fees_cents = 0
    interest_cents = 0
    principal_cents = 0
    deltas: dict[str, dict[str, int]] = {}

    def _ensure(inst_id):
        if inst_id not in deltas:
            deltas[inst_id] = {"principal": 0, "interest": 0, "fees": 0}
        return deltas[inst_id]

    # ── Step 1: servicing fee on scheduled interest currently due ──────────
    interest_due_total = 0
    for inst in installments:
        if inst["status"] in ("DUE", "LATE"):
            outstanding_interest = max(
                inst["scheduled_interest_cents"] - inst["paid_interest_cents"], 0
            )
            interest_due_total += outstanding_interest
    fee = servicing_fee_cents(interest_due_total, servicing_fee_bps)
    take = min(fee, remaining)
    fees_cents += take
    remaining -= take

    # ── Step 2: late fees on currently-LATE installments oldest first ──────
    if remaining > 0:
        for inst in installments:
            if inst["status"] != "LATE":
                continue
            # Each LATE installment carries a flat per-event late fee debt that
            # is still owed if its paid_fees_cents has not yet absorbed it.
            owed_late_fee = max(late_fee_cents_per_event - inst["paid_fees_cents"], 0)
            take = min(owed_late_fee, remaining)
            if take > 0:
                _ensure(inst["id"])["fees"] += take
                late_fees_cents += take
                remaining -= take
            if remaining <= 0:
                break

    # ── Step 3: scheduled interest on overdue installments oldest first ────
    if remaining > 0:
        for inst in installments:
            if inst["status"] not in ("LATE", "DUE"):
                continue
            owed = max(inst["scheduled_interest_cents"] - inst["paid_interest_cents"], 0)
            # Net-of-fee allocation: the bucket consumes the full owed interest
            # (the servicing fee is conceptually pre-deducted from the payment,
            # not from the per-installment interest target).
            take = min(owed, remaining)
            if take > 0:
                _ensure(inst["id"])["interest"] += take
                interest_cents += take
                remaining -= take
            if remaining <= 0:
                break

    # ── Step 4: scheduled principal on overdue installments oldest first ───
    if remaining > 0:
        for inst in installments:
            if inst["status"] not in ("LATE", "DUE"):
                continue
            owed = max(inst["scheduled_principal_cents"] - inst["paid_principal_cents"], 0)
            take = min(owed, remaining)
            if take > 0:
                _ensure(inst["id"])["principal"] += take
                principal_cents += take
                remaining -= take
            if remaining <= 0:
                break

    # ── Step 5: prepayment principal on next SCHEDULED installment ─────────
    if remaining > 0:
        for inst in installments:
            if inst["status"] != "SCHEDULED":
                continue
            owed = max(inst["scheduled_principal_cents"] - inst["paid_principal_cents"], 0)
            take = min(owed, remaining)
            if take > 0:
                _ensure(inst["id"])["principal"] += take
                principal_cents += take
                remaining -= take
            if remaining <= 0:
                break
            # After fully prepaying this one, continue to the next scheduled
            # installment until payment is exhausted or there are none left.

    allocation = {
        "fees_cents": fees_cents,
        "interest_cents": interest_cents,
        "principal_cents": principal_cents,
        "late_fees_cents": late_fees_cents,
        "unallocated_cents": max(remaining, 0),
    }
    return allocation, deltas
