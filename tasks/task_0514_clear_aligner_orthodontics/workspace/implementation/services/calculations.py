"""Calculation rules (SCAFFOLD §1.3, PRD §3.5/§3.7/§3.11/§3.9/§3.1).

All monetary results are integer cents, round_half_up at each pinned step.
"""
from decimal import Decimal

from services.money import round_half_up

# ---- case_price constants ----
IN_OFFICE_SCAN_SURCHARGE_CENTS = 25000
LIGHT_MULT = Decimal("0.80")
MODERATE_MULT = Decimal("1.00")
COMPLEX_MULT = Decimal("1.35")

# ---- refund_amount constants ----
RESTOCK_FEE_CENTS = 7500

# ---- refinement_fee constants ----
INCLUDED_REFINEMENTS = 1
REFINEMENT_FEE_CENTS = 30000

# ---- delinquency constants ----
DEFAULT_THRESHOLD = 3

# ---- intake usability gate ----
MIN_USABLE_QUALITY = 0.60

# ---- delinquency-sweep grace period ----
GRACE_DAYS = 5

# ---- express buffer ----
EXPRESS_BUFFER_HOURS = 24


def case_price(list_price_cents, intake_channel, proposed_step_count, discount_code):
    """Contracted total in cents (PRD §3.5). Pinned order:
    base -> channel surcharge -> tier multiply (round) -> discount (round) -> floor 0."""
    base = list_price_cents
    if intake_channel == "IN_OFFICE_SCAN":
        base = base + IN_OFFICE_SCAN_SURCHARGE_CENTS

    if proposed_step_count <= 14:
        tier_mult = LIGHT_MULT
    elif proposed_step_count <= 28:
        tier_mult = MODERATE_MULT
    else:
        tier_mult = COMPLEX_MULT

    tiered = round_half_up(Decimal(base) * tier_mult)

    if discount_code == "WELCOME15":
        disc = round_half_up(Decimal(tiered) * Decimal("0.15"))
    elif discount_code == "FLAT200":
        disc = 20000
    else:
        disc = 0

    return max(tiered - disc, 0)


def amortization(financed_principal_cents, term_months, apr_bps):
    """Generate the installment schedule (PRD §3.7 amortization).

    Returns a list of dicts: {sequence_no, amount_cents, principal_portion_cents}.
    Pinned: per-installment rounding for installments 1..n-1; the final
    installment absorbs the residual so principal portions sum exactly to P.
    """
    P = financed_principal_cents
    n = term_months
    rows = []

    if apr_bps == 0:
        base_payment = round_half_up(Decimal(P) / Decimal(n))
        # straight-line: principal portion == amount, no interest
        running_principal = 0
        total_interest = 0
        for seq in range(1, n):
            rows.append({
                "sequence_no": seq,
                "amount_cents": base_payment,
                "principal_portion_cents": base_payment,
            })
            running_principal += base_payment
        # final installment absorbs residual
        final_amount = P + total_interest - running_principal
        final_principal = P - running_principal
        rows.append({
            "sequence_no": n,
            "amount_cents": final_amount,
            "principal_portion_cents": final_principal,
        })
        return rows

    monthly_rate = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    one_plus = Decimal(1) + monthly_rate
    pow_n = one_plus ** n
    factor = (monthly_rate * pow_n) / (pow_n - Decimal(1))
    base_payment = round_half_up(Decimal(P) * factor)

    running_balance = Decimal(P)
    sum_interest = Decimal(0)
    sum_amounts = 0
    for seq in range(1, n):
        interest = round_half_up(running_balance * monthly_rate)
        principal_portion = base_payment - interest
        running_balance -= Decimal(principal_portion)
        sum_interest += Decimal(interest)
        sum_amounts += base_payment
        rows.append({
            "sequence_no": seq,
            "amount_cents": base_payment,
            "principal_portion_cents": principal_portion,
        })

    # Final installment: amount absorbs residual; principal portion makes the
    # schedule's principal portions sum exactly to P.
    # interest on final installment uses the remaining running_balance.
    final_interest = round_half_up(running_balance * monthly_rate)
    sum_interest += Decimal(final_interest)
    total_scheduled_interest = sum_interest
    final_amount = P + int(total_scheduled_interest) - sum_amounts
    sum_principal_so_far = sum(r["principal_portion_cents"] for r in rows)
    final_principal = P - sum_principal_so_far
    rows.append({
        "sequence_no": n,
        "amount_cents": final_amount,
        "principal_portion_cents": final_principal,
    })
    return rows


def delinquency_state(late_count):
    """Decide delinquency_state from the LATE installment count (PRD §3.7)."""
    if late_count >= DEFAULT_THRESHOLD:
        return "DEFAULTED"
    elif late_count >= 1:
        return "DELINQUENT"
    return "CURRENT"


def refund_amount(reason, amount_collected_cents, total_contracted_cents,
                  shipped_first_run, total_first_run_non_void):
    """Compute (computed_refund_cents, restocking_fee_cents) per PRD §3.11."""
    if reason == "ELIGIBILITY_DECLINE":
        return amount_collected_cents, 0
    if reason == "GOODWILL":
        return amount_collected_cents, 0
    # PATIENT_CANCEL
    # total_first_run_non_void guaranteed >= 1 post-approval
    used_fraction = Decimal(shipped_first_run) / Decimal(total_first_run_non_void)
    consumed = round_half_up(Decimal(total_contracted_cents) * used_fraction)
    restocking = RESTOCK_FEE_CENTS
    refund = max(amount_collected_cents - consumed - restocking, 0)
    return refund, restocking
