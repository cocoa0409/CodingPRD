"""Pricing-engine calculations (PRD §3.3, §3.7, §3.9; SCAFFOLD §1.3).

All money is integer cents. Every named rounding step uses round-half-up,
applied at that individual point (not just at the end). Truck fractions use
Decimal internally to keep eighth-step arithmetic exact.
"""
from decimal import Decimal
from util import round_half_up

# Per-category surcharge field on the policy, keyed by JobItem/declared category.
_SURCHARGE_FIELD = {
    "MATTRESS": "mattress_surcharge_cents",
    "APPLIANCE": "appliance_surcharge_cents",
    "FREON_APPLIANCE": "freon_surcharge_cents",
    # STANDARD carries no surcharge.
}


def billed_fraction(raw, policy):
    """Round raw UP to next multiple of fraction_step, then floor at min_billable_fraction.

    Result is an exact multiple of fraction_step (PRD §2.8, §3.3).
    """
    from decimal import ROUND_CEILING
    step = Decimal(str(policy["fraction_step"]))
    raw_d = Decimal(str(raw))
    # ceil(raw / step): round the quotient UP to the next whole number of steps.
    q = raw_d / step
    steps = q.to_integral_value(rounding=ROUND_CEILING)
    billed = steps * step
    floor = Decimal(str(policy["min_billable_fraction"]))
    if billed < floor:
        billed = floor
    return billed  # Decimal


def base_haul_cents(billed, policy):
    """Tiered marginal-band base haul cost over full_truck_cents, then rounded.

    billed: Decimal billed fraction. tier_breaks: ordered bands [{upper_fraction,
    marginal_multiplier}] starting at 0 and ending at upper_fraction 1.0.
    """
    full = Decimal(str(policy["full_truck_cents"]))
    bands = policy["tier_breaks"]
    base = Decimal("0")
    prev_upper = Decimal("0")
    for band in bands:
        upper = Decimal(str(band["upper_fraction"]))
        mult = Decimal(str(band["marginal_multiplier"]))
        capped = billed if billed < upper else upper
        band_amount = capped - prev_upper
        if band_amount < 0:
            band_amount = Decimal("0")
        base += band_amount * full * mult
        prev_upper = upper
    return round_half_up(base)


def surcharge_total_cents(items, policy):
    """Sum per-item surcharge; round per item (rate*quantity) before summing.

    items: iterable of dicts with category + quantity.
    """
    total = 0
    for it in items:
        category = it.get("category")
        field = _SURCHARGE_FIELD.get(category)
        if field is None:
            continue  # STANDARD or unknown -> no surcharge
        rate = policy[field]
        qty = it.get("quantity", 1)
        total += round_half_up(Decimal(str(rate)) * Decimal(str(qty)))
    return total


def estimated_truck_fraction(accepted_estimate, policy):
    """Billed fraction derived from the accepted estimate's raw_fraction.

    Returned as a float for storage/serialization (exact multiple of step).
    """
    bf = billed_fraction(accepted_estimate["raw_fraction"], policy)
    return float(bf)


def estimated_total_cents(job, accepted_estimate, policy):
    """Estimate-variant total: base + same-day uplift + declared-item surcharge.

    Excludes dump fees, diversion credits, recycling fees, and tax (unknown
    pre-load). PRD §3.3.
    """
    bf = billed_fraction(accepted_estimate["raw_fraction"], policy)
    base = base_haul_cents(bf, policy)
    if job["service_type"] == "SAME_DAY":
        uplift = round_half_up(Decimal(str(base)) * Decimal(str(policy["same_day_surcharge_pct"])))
        base = base + uplift
    surcharge = surcharge_total_cents(accepted_estimate.get("declared_items") or [], policy)
    return base + surcharge


def dump_fee_for_ticket(ticket, policy):
    """Per-ticket pass-through fee by fee_basis (PRD §3.7)."""
    if ticket["fee_basis"] == "WEIGHT_BASED":
        return round_half_up(Decimal(str(ticket["landfill_tons"])) *
                             Decimal(str(policy["dump_fee_per_ton_cents"])))
    else:  # VOLUME_BASED
        return round_half_up(Decimal(str(ticket["landfill_fraction"])) *
                             Decimal(str(policy["full_truck_dump_cents"])))


def final_total_cents(job, items, dump_tickets, diversion_records, policy):
    """Final-variant total from measured fraction + actual manifest (PRD §3.7).

    Assumes each dump ticket's dump_fee_cents has already been computed and stored.
    """
    bf = billed_fraction(job["measured_truck_fraction"], policy)
    base = base_haul_cents(bf, policy)
    if job["service_type"] == "SAME_DAY":
        uplift = round_half_up(Decimal(str(base)) * Decimal(str(policy["same_day_surcharge_pct"])))
        base = base + uplift
    surcharge = surcharge_total_cents(items, policy)
    dump = sum(dt["dump_fee_cents"] for dt in dump_tickets)
    recycle = 0
    credit = 0
    for dr in diversion_records:
        if dr["destination"] == "RECYCLING":
            recycle += round_half_up(Decimal(str(dr["tons"])) *
                                     Decimal(str(policy["recycle_fee_per_ton_cents"])))
        credit += round_half_up(Decimal(str(dr["tons"])) *
                                Decimal(str(policy["diversion_credit_per_ton_cents"])))
    subtotal = base + surcharge + dump + recycle - credit
    tax = round_half_up(Decimal(str(subtotal)) * Decimal(str(policy["tax_pct"])))
    return subtotal + tax


def cancellation_fee(job, policy):
    """Fee by job status at cancel time (PRD §3.9)."""
    s = job["status"]
    if s == "ESTIMATED":
        return 0
    if s == "SCHEDULED":
        return round_half_up(Decimal(str(job["estimated_total_cents"])) *
                             Decimal(str(policy["cancel_pct_scheduled"])))
    if s == "DISPATCHED":
        return round_half_up(Decimal(str(job["estimated_total_cents"])) *
                             Decimal(str(policy["cancel_pct_dispatched"])))
    return 0
