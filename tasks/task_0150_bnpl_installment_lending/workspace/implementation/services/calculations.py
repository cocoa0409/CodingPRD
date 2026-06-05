"""Pure calculation routines (SCAFFOLD §1.3, PRD §3).

All monetary amounts are integer cents. Rounding is round-half-up unless a rule
calls for floor/cap. Days are whole-integer floors of elapsed-time / one day.
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants pinned by the scaffold.
MONTHLY_APR_BPS = 1990
PAY_IN_4_INTERVAL_DAYS = 14
MONTHLY_INTERVAL_DAYS = 30

# Eligibility tiers.
SCORE_TIER_1 = 580
SCORE_TIER_2 = 670
SCORE_TIER_3 = 740
LIMIT_TIER_2_CENTS = 50000
LIMIT_TIER_3_CENTS = 200000
LIMIT_TIER_4_CENTS = 500000
INCOME_FACTOR = Decimal("0.10")

# Late fee / delinquency.
GRACE_DAYS = 10
DELINQUENT_DAYS = 30
LATE_FEE_RATE = Decimal("0.05")
LATE_FEE_FLOOR_CENTS = 700
LATE_FEE_CAP_CENTS = 1500


def round_half_up(value):
    """Round a numeric value to the nearest integer, halves away from zero (up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ── eligibility_limit ─────────────────────────────────────────────────────────
def provisional_eligible_limit(soft_credit_score, annual_income_cents):
    """Provisional soft-credit limit set once at registration (PRD §3.1)."""
    score = soft_credit_score
    if score < SCORE_TIER_1:
        base_limit = 0
    elif score < SCORE_TIER_2:
        base_limit = LIMIT_TIER_2_CENTS
    elif score < SCORE_TIER_3:
        base_limit = LIMIT_TIER_3_CENTS
    else:
        base_limit = LIMIT_TIER_4_CENTS
    # income_cap = floor(0.10 * annual_income_cents)
    income_cap = int((Decimal(annual_income_cents) * INCOME_FACTOR).to_integral_value(
        rounding="ROUND_FLOOR"))
    return min(base_limit, income_cap)


# ── finance_charge / installment_schedule ─────────────────────────────────────
def apr_bps_for_plan(plan_type):
    return 0 if plan_type == "PAY_IN_4" else MONTHLY_APR_BPS


def build_schedule(principal, plan_type, term_months):
    """Build the installment schedule for a financed principal.

    Returns a list of dicts (one per installment, in sequence order):
      { "sequence_no", "offset_days", "amount_due_cents", "principal_portion_cents" }

    PAY_IN_4: zero interest, even split with residual on installment #4, four
              bi-weekly due offsets {0,14,28,42}.
    MONTHLY:  amortized at 19.90% APR over N installments; per-installment
              interest on the declining balance; final installment absorbs the
              rounding residual on both amount_due and principal_portion.
    """
    P = principal
    rows = []

    if plan_type == "PAY_IN_4":
        base = P // 4
        residual = P - base * 4
        offsets = [0, PAY_IN_4_INTERVAL_DAYS, PAY_IN_4_INTERVAL_DAYS * 2,
                   PAY_IN_4_INTERVAL_DAYS * 3]  # 0, 14, 28, 42
        for i in range(4):
            amt = base + (residual if i == 3 else 0)
            rows.append({
                "sequence_no": i + 1,
                "offset_days": offsets[i],
                "amount_due_cents": amt,
                "principal_portion_cents": amt,  # zero interest
            })
        return rows

    # MONTHLY amortized.
    N = term_months
    r = (Decimal(MONTHLY_APR_BPS) / Decimal(10000) / Decimal(12))  # monthly periodic rate
    Pd = Decimal(P)
    if r == 0:
        pmt = Pd / Decimal(N)
    else:
        one_plus_r_n = (Decimal(1) + r) ** N
        pmt = Pd * r * one_plus_r_n / (one_plus_r_n - Decimal(1))

    amount_due = []
    for i in range(1, N):  # installments 1..N-1
        amount_due.append(round_half_up(pmt))
    # total_of_payments_cents derived from the rounded schedule (see finance charge).
    # The final installment absorbs the residual so the amounts sum to the total of
    # payments. The total of payments = financed_principal + finance_charge, and the
    # finance charge is the sum of per-installment interest. To compute the schedule
    # self-consistently we first need the full set of amount_due values; the last is
    # set so the *principal portions* sum exactly to P (see below) and the amount_due
    # absorbs the interest residual. We derive the last amount_due via the running
    # balance interest accounting, which is exact.

    # Compute per-installment interest on the declining balance for 1..N-1, and the
    # principal portions; the final installment then absorbs whatever balance remains.
    bal = Pd
    principal_portion = []
    for i in range(N - 1):
        interest_i = round_half_up(bal * r)
        pp = amount_due[i] - interest_i
        principal_portion.append(pp)
        bal -= Decimal(pp)
    # Final installment: principal portion = remaining balance; interest on remaining
    # balance; amount_due = principal_portion + interest. This guarantees principal
    # portions sum to P exactly and the schedule total equals principal + total interest.
    final_interest = round_half_up(bal * r)
    final_principal = int(bal)  # remaining balance is whole cents (sum is exact)
    final_amount_due = final_principal + final_interest
    amount_due.append(final_amount_due)
    principal_portion.append(final_principal)

    for i in range(N):
        rows.append({
            "sequence_no": i + 1,
            "offset_days": (i + 1) * MONTHLY_INTERVAL_DAYS,
            "amount_due_cents": amount_due[i],
            "principal_portion_cents": principal_portion[i],
        })
    return rows


def finance_figures(cart_amount_cents, down_payment_cents, plan_type, term_months):
    """Compute (apr_bps, financed_principal, finance_charge, total_of_payments)
    using the pinned evaluation order (PRD §3.2 / SCAFFOLD finance_charge)."""
    apr_bps = apr_bps_for_plan(plan_type)
    financed_principal = cart_amount_cents - down_payment_cents
    schedule = build_schedule(financed_principal, plan_type, term_months)
    total_due = sum(row["amount_due_cents"] for row in schedule)
    finance_charge = total_due - financed_principal
    total_of_payments = financed_principal + finance_charge
    return apr_bps, financed_principal, finance_charge, total_of_payments


# ── late_fee_assessment ───────────────────────────────────────────────────────
def late_fee_for(outstanding_cents):
    raw = round_half_up(Decimal(outstanding_cents) * LATE_FEE_RATE)
    return min(LATE_FEE_CAP_CENTS, max(LATE_FEE_FLOOR_CENTS, raw))


# ── merchant settlement net ───────────────────────────────────────────────────
def mdr_fee(gross_cents, mdr_bps):
    return round_half_up(Decimal(gross_cents) * Decimal(mdr_bps) / Decimal(10000))


# ── days past due ─────────────────────────────────────────────────────────────
def days_between(now_dt, due_dt):
    """floor((now - due) / 1 day), may be negative."""
    delta = now_dt - due_dt
    total_seconds = delta.total_seconds()
    return int(total_seconds // 86400)
