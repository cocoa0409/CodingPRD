"""Calculation: return_premium_and_tax_adjustment (PRD 3.8).

Three cancellation types earn premium differently, a minimum earned premium
floor can override the type figure entirely, and each state decides
independently whether its premium tax and its stamping fee are refundable.
Refunds always use the rates PINNED on the allocation rows.
"""

import store
from errors import ApiError
from moneyutil import dec, largest_remainder, normalised_weights, round_half_up

SHORT_RATE_FACTOR = dec("0.90")


def whole_days(start, end):
    """Whole calendar days from start to end, floored."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


def compute(policy, cancellation):
    """Returns a dict of the cancellation's computed figures plus per-state parts."""
    effective = policy.get("_effective_at")
    expiration = policy.get("_expiration_at")
    cancel_at = cancellation.get("_cancellation_at")

    term_days = whole_days(effective, expiration)
    elapsed_days = whole_days(effective, cancel_at)
    if elapsed_days < 0 or elapsed_days > term_days:
        raise ApiError("ERR_CANCELLATION_DATE_OUT_OF_TERM",
                       "cancellation_date lies outside the policy term.")
    unearned_days = term_days - elapsed_days

    taxable = int(policy.get("taxable_premium_cents") or 0)
    ctype = cancellation.get("cancellation_type")

    # Step 1 - unearned premium by cancellation type.
    if ctype == "FLAT":
        if elapsed_days != 0:
            raise ApiError("ERR_FLAT_CANCELLATION_NOT_AVAILABLE",
                           "A flat cancellation is available only on the "
                           "effective date itself.")
        unearned = taxable
    elif term_days <= 0:
        unearned = taxable
    elif ctype == "PRO_RATA":
        unearned = round_half_up(dec(taxable) * dec(unearned_days) / dec(term_days))
    else:  # SHORT_RATE
        unearned = round_half_up(dec(taxable) * dec(unearned_days) / dec(term_days)
                                 * SHORT_RATE_FACTOR)

    # Step 2 - the minimum earned premium floor may override the type figure.
    min_earned = round_half_up(dec(taxable) * dec(policy.get("min_earned_premium_pct")))
    if taxable - unearned < min_earned:
        unearned = max(0, taxable - min_earned)

    return_premium = unearned
    earned = taxable - unearned

    # Step 3 - per-state tax and stamping refunds over the PINNED percentages.
    rows = store.allocations_of(policy["id"])
    parts = largest_remainder(return_premium, normalised_weights(rows)) if rows else {}

    tax_refund = 0
    stamping_refund = 0
    per_state = []
    for row in rows:
        code = row.get("state_code")
        part = int(parts.get(code, 0))
        program = store.state_program_by_code(code)

        if program is not None and program.get("return_premium_tax_refundable"):
            tax_part = round_half_up(dec(part) * dec(row.get("premium_tax_rate_applied")))
        else:
            tax_part = 0

        row_fee = int(row.get("stamping_fee_cents") or 0)
        if program is not None and program.get("return_premium_stamping_refundable") \
                and row_fee > 0:
            fee_part = round_half_up(dec(part) * dec(row.get("stamping_fee_rate_applied")))
            fee_part = min(fee_part, row_fee)
        else:
            fee_part = 0

        tax_refund += tax_part
        stamping_refund += fee_part
        per_state.append({
            "state_code": code,
            "state_program_id": row.get("_state_program_id"),
            "return_premium_cents": part,
            "tax_refund_cents": tax_part,
            "stamping_fee_refund_cents": fee_part,
        })

    return {
        "earned_premium_cents": earned,
        "return_premium_cents": return_premium,
        "tax_refund_cents": tax_refund,
        "stamping_fee_refund_cents": stamping_refund,
        "per_state": per_state,
    }
