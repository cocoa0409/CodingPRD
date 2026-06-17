"""Billing calculations (PRD section 3.9). All integer cents; no rounding."""

# Contamination fee constants (PRD section 3.9 / scaffold §1.3).
TIRES_FLAT_CENTS = 7500
APPLIANCES_FLAT_CENTS = 12000
HAZMAT_FLAT_CENTS = 50000
HAZMAT_SURCHARGE_CENTS_PER_LB = 15


def overage_day_charge(rental_days, ctype):
    """billable_overage_days = max(0, rental_days - included_days)."""
    billable = max(0, rental_days - ctype["included_days"])
    return billable * ctype["overage_day_cents"]


def tonnage_overage_charge(weight_lbs, ctype):
    """billable_overage_lbs = max(0, weight_lbs - included_tonnage_lbs)."""
    billable = max(0, weight_lbs - ctype["included_tonnage_lbs"])
    return billable * ctype["overage_rate_cents_per_lb"]


def contamination_fee(ticket, net_weight_lbs, ctype):
    """Flat per-kind, plus a per-overage-lb surcharge for HAZMAT.

    The HAZMAT surcharge applies to the SAME overage pounds billed in the
    final tonnage charge: max(0, net_weight_lbs - included_tonnage_lbs).
    """
    if not ticket["contaminated"] or ticket["contamination_kind"] == "NONE":
        return 0
    kind = ticket["contamination_kind"]
    if kind == "TIRES":
        return TIRES_FLAT_CENTS
    if kind == "APPLIANCES":
        return APPLIANCES_FLAT_CENTS
    if kind == "HAZMAT":
        billable_overage_lbs = max(0, net_weight_lbs - ctype["included_tonnage_lbs"])
        return HAZMAT_FLAT_CENTS + billable_overage_lbs * HAZMAT_SURCHARGE_CENTS_PER_LB
    return 0


def approved_permit_fee(order_id, permits):
    """permit charge = APPROVED StreetPermit.permit_fee_cents for the order, else 0.

    If multiple approved permits exist on the order, sum is not implied by PRD;
    the PRD speaks of 'an APPROVED permit' singular — use the first approved
    permit's fee. Overlapping approvals are prevented at approval time, so at
    most one approved permit window covers any single date, but the line item
    is simply 'the APPROVED permit's fee'.
    """
    for p in permits:
        if p["order_id"] == order_id and p["status"] == "APPROVED":
            return p["permit_fee_cents"]
    return 0


def estimated_charge(base_cents, overage_day_cents, tonnage_cents_estimated, permit_cents):
    """estimated_total = base + overage_day + tonnage(estimate) + permit."""
    return base_cents + overage_day_cents + tonnage_cents_estimated + permit_cents


def final_charge(base_cents, overage_day_cents, tonnage_cents_final,
                 permit_cents, contamination_cents):
    """final_total = base + overage_day + tonnage(final) + permit + contamination."""
    return (base_cents + overage_day_cents + tonnage_cents_final
            + permit_cents + contamination_cents)
