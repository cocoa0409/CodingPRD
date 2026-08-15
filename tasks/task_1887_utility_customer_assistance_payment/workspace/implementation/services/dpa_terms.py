"""DPA terms computation (calc: dpa_terms_computation) — snapshot semantics,
pinned evaluation order, integer cents with round-half-up."""

from fractions import Fraction

from services.common import round_half_up, active_enrollment

MIN_ARREARAGE_CENTS = 10000
FORGIVENESS_SHARE = {
    "TIER_1": Fraction(1, 2),
    "TIER_2": Fraction(1, 3),
    "TIER_3": Fraction(1, 4),
    "NONE": Fraction(0, 1),
}
DOWN_MIN_TIER_2_CENTS = 2500
DOWN_MIN_OTHER_CENTS = 5000


def compute_terms(account, installment_count):
    """Returns dict of DPA term fields. Evaluation order pinned top-to-bottom."""
    # 1. snapshot
    covered = account["arrearage_balance_cents"]
    # 2. tier lookup
    enrollment = active_enrollment(account["id"])
    tier = enrollment["tier"] if enrollment else "NONE"
    # 3. down payment
    if tier == "TIER_1":
        down = 0
    elif tier == "TIER_2":
        down = max(round_half_up(Fraction(covered) * Fraction(5, 100)),
                   DOWN_MIN_TIER_2_CENTS)
    else:  # TIER_3 or NONE
        down = max(round_half_up(Fraction(covered) * Fraction(10, 100)),
                   DOWN_MIN_OTHER_CENTS)
    # 4. forgiveness pool
    pool = round_half_up(Fraction(covered) * FORGIVENESS_SHARE[tier])
    # 5. installment base + equal installment
    base = covered - down - pool
    n = installment_count
    inst = round_half_up(Fraction(base, n))
    # 6. final installment absorbs rounding remainder
    final = base - (n - 1) * inst
    return {
        "covered_arrearage_cents": covered,
        "down_payment_required_cents": down,
        "forgiveness_pool_cents": pool,
        "installment_amount_cents": inst,
        "final_installment_amount_cents": final,
        "projected_forgiveness_cents": pool,
    }
