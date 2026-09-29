"""The seven calculations of the guaranty association API.

All money is integer cents.  Round-half-up applies in exactly four places
(PRD 2.5): the per-member assessment cap, each raw unearned premium refund
variant, the projected recoupment, and a single vendor invoice fee.  Pro-rata
distribution shares and raw assessment shares are truncated downward with
deterministic residual-cent hand-out.
"""

from fractions import Fraction

SHORT_RATE_FACTOR = Fraction(9, 10)
MAX_REDISTRIBUTION_ROUNDS = 3
MAX_AGGREGATE_SURCHARGE_BPS = 300
DEFAULT_ANNUAL_CAP_RATE_BPS = 200
ASSOCIATION_STATE_CODE = "MI"


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) in exact integer arithmetic."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def round_half_up_fraction(value):
    """round_half_up of a Fraction / int to a whole cent."""
    frac = Fraction(value)
    return round_half_up_div(frac.numerator, frac.denominator)


def to_fraction(value):
    """Exact Fraction from an int or a JSON float (via its decimal text)."""
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


# --------------------------------------------------------------------------
# calculation 1: claim_net_payable
# --------------------------------------------------------------------------
def claim_net_payable(claim, policy, profile, other_recoverable, aggregate_paid_excluding):
    """PRD 3.4 -- returns the six computed terms of the statutory net payable."""
    gross = int(claim.get("gross_loss_cents") or 0)
    punitive = int(claim.get("punitive_damages_cents") or 0)

    covers_punitive = bool(profile.get("covers_punitive_damages")) if profile else False
    covered_basis = gross + (punitive if covers_punitive else 0)

    large_deductible = int(policy.get("large_deductible_cents") or 0)
    sir = int(policy.get("self_insured_retention_cents") or 0)
    collateral = int(policy.get("collateral_held_cents") or 0)
    attachment_point = min(large_deductible + sir, collateral)

    covered_layer = max(0, covered_basis - attachment_point)

    other = int(other_recoverable or 0)
    deductible = int(profile.get("statutory_deductible_cents") or 0) if profile else 0
    per_claim_cap = int(profile.get("per_claim_cap_cents") or 0) if profile else 0
    aggregate_cap = int(profile.get("per_policy_aggregate_cap_cents") or 0) if profile else 0
    mode = profile.get("cap_order_mode") if profile else "OFFSET_THEN_CAP"

    if mode == "OFFSET_THEN_CAP":
        statutory = max(0, min(covered_layer - other - deductible, per_claim_cap))
        alternate = max(0, min(covered_layer, per_claim_cap) - other - deductible)
    else:  # CAP_THEN_OFFSET
        statutory = max(0, min(covered_layer, per_claim_cap) - other - deductible)
        alternate = max(0, min(covered_layer - other - deductible, per_claim_cap))

    remaining_aggregate = max(0, aggregate_cap - int(aggregate_paid_excluding or 0))
    net_payable = min(statutory, remaining_aggregate)
    uncapped = max(0, covered_layer - other - deductible)

    if net_payable < statutory:
        cap_binding = "PER_POLICY_AGGREGATE"
    elif uncapped > per_claim_cap:
        cap_binding = "PER_CLAIM"
    else:
        cap_binding = "NONE"

    return {
        "covered_basis_cents": covered_basis,
        "attachment_point_cents": attachment_point,
        "covered_layer_cents": covered_layer,
        "other_insurance_recoverable_cents": other,
        "statutory_deductible_cents": deductible,
        "per_claim_cap_cents": per_claim_cap,
        "remaining_aggregate_cents": remaining_aggregate,
        "statutory_cents": statutory,
        "net_payable_cents": net_payable,
        "alt_net_payable_cents": alternate,
        "cap_binding": cap_binding,
    }


# --------------------------------------------------------------------------
# calculation 2: unearned_premium_refund
# --------------------------------------------------------------------------
def unearned_premium_refund(annual_premium_cents, unexpired_days, term_days, refund_method, cap_cents):
    """PRD 3.3 -- both variants, each rounded half up exactly once, then capped."""
    premium = int(annual_premium_cents or 0)
    unexpired = int(unexpired_days or 0)
    term = int(term_days or 0)

    if term <= 0:
        pro_rata_raw = 0
        short_rate_raw = 0
    else:
        pro_rata_raw = round_half_up_div(premium * unexpired, term)
        # the short-rate factor multiplies the unrounded quotient
        short_rate_raw = round_half_up_div(premium * unexpired * 9, term * 10)

    if refund_method == "PRO_RATA":
        elected_raw, other_raw = pro_rata_raw, short_rate_raw
    else:
        elected_raw, other_raw = short_rate_raw, pro_rata_raw

    cap = int(cap_cents or 0)
    return {
        "pro_rata_raw_cents": pro_rata_raw,
        "short_rate_raw_cents": short_rate_raw,
        "computed_refund_cents": min(elected_raw, cap),
        "alt_refund_cents": min(other_raw, cap),
        "capped": elected_raw > cap,
    }


# --------------------------------------------------------------------------
# calculation 3: distribution_waterfall
# --------------------------------------------------------------------------
def allocate(funds, outstanding_list):
    """Return the list of allocations and the funds left over.

    Full satisfaction when funds >= total (no rounding at all); otherwise
    pro-rata with floored shares and residual cents handed out one at a time in
    the class's own declared ordering.
    """
    total = sum(outstanding_list)
    if total <= 0:
        return [0 for _ in outstanding_list], funds
    if funds >= total:
        return list(outstanding_list), funds - total
    shares = [(funds * out) // total for out in outstanding_list]
    remainder = funds - sum(shares)
    index = 0
    while remainder > 0 and shares:
        shares[index] += 1
        remainder -= 1
        index = (index + 1) % len(shares)
    return shares, 0


# --------------------------------------------------------------------------
# calculation 4: member_assessment_allocation
# --------------------------------------------------------------------------
def member_assessment_allocation(members, needed_amount_cents):
    """PRD 3.9 -- capped redistribution over at most three rounds.

    `members` must already be ordered by created_at ASC then sequence ASC.
    Returns a list of dicts in the same order as `members`.
    """
    caps = {}
    for member in members:
        base = int(member.get("direct_written_premium_cents") or 0)
        bps = int(member.get("annual_cap_rate_bps") or 0)
        caps[member["id"]] = round_half_up_div(base * bps, 10000)

    pool = list(members)
    need = int(needed_amount_cents)
    allocated = {}
    decision_raw = {}
    raw = {}

    for _ in range(MAX_REDISTRIBUTION_ROUNDS):
        if not pool:
            break
        total_base = sum(int(m.get("direct_written_premium_cents") or 0) for m in pool)
        if total_base == 0:
            break
        raw = {}
        for member in pool:
            base = int(member.get("direct_written_premium_cents") or 0)
            raw[member["id"]] = (need * base) // total_base
        remainder = need - sum(raw.values())
        index = 0
        while remainder > 0 and pool:
            member = pool[index % len(pool)]
            raw[member["id"]] += 1
            remainder -= 1
            index += 1
        newly_capped = [m for m in pool if raw[m["id"]] > caps[m["id"]]]
        if not newly_capped:
            for member in pool:
                allocated[member["id"]] = raw[member["id"]]
                decision_raw[member["id"]] = raw[member["id"]]
            pool = []
            break
        for member in newly_capped:
            allocated[member["id"]] = caps[member["id"]]
            decision_raw[member["id"]] = raw[member["id"]]
            need -= caps[member["id"]]
            pool.remove(member)

    for member in pool:
        member_raw = raw.get(member["id"], 0)
        allocated[member["id"]] = min(member_raw, caps[member["id"]])
        decision_raw[member["id"]] = member_raw

    result = []
    for member in members:
        cap = caps[member["id"]]
        levied = allocated.get(member["id"], 0)
        raw_share = decision_raw.get(member["id"], 0)
        result.append(
            {
                "member": member,
                "cap_amount_cents": cap,
                "levied_amount_cents": levied,
                "capped": levied == cap and raw_share > cap,
            }
        )
    return result


# --------------------------------------------------------------------------
# calculation 5: recoupment_surcharge_projection
# --------------------------------------------------------------------------
def recoupment_surcharge_projection(surcharge_base_cents, surcharge_rate_bps, levied_amount_cents):
    projected = round_half_up_div(int(surcharge_base_cents) * int(surcharge_rate_bps), 10000)
    return min(projected, int(levied_amount_cents))


# --------------------------------------------------------------------------
# calculation 7: vendor_fee_accrual
# --------------------------------------------------------------------------
def vendor_invoice_fee(hours, hourly_rate_cents):
    return round_half_up_fraction(to_fraction(hours) * Fraction(int(hourly_rate_cents)))


def add_hours(current, hours):
    total = to_fraction(current or 0) + to_fraction(hours)
    if total.denominator == 1:
        return int(total)
    return float(total)
