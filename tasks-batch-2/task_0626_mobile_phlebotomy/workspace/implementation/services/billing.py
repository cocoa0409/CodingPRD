"""Billing calculations (PRD 3.10, scaffold calculations).

All money is integer cents; all arithmetic in cents, no fractional rounding
(PRD 2.9). Negative results floored at zero.
"""

# Self-pay constants (scaffold invoice_self_pay_total).
SELF_PAY_BASE_CONVENIENCE_CENTS = 3500
SELF_PAY_PER_TUBE_CENTS = 500
SELF_PAY_REDRAW_WAIVER_UNIT_CENTS = 1000

# Insurance constants (scaffold invoice_insurance_total).
INSURANCE_FLAT_CONVENIENCE_CENTS = 2500
INSURANCE_REDRAW_WAIVER_UNIT_CENTS = 2500


def lab_fee_cents(panel, partner, priority):
    """PRD 3.10: base_lab_fee_cents plus stat_surcharge_cents when priority == STAT."""
    fee = panel["base_lab_fee_cents"]
    if priority == "STAT":
        fee += partner["stat_surcharge_cents"]
    return fee


def compute_billing(billing_mode, panel, partner, priority, redraw_count):
    """Return (lab_fee_cents, convenience_fee_cents, redraw_waiver_cents, total_cents).

    Shared by Invoice issue and the LabOrder forward-looking estimate; the only
    difference is the caller's redraw_count input.
    """
    fee = lab_fee_cents(panel, partner, priority)

    if billing_mode == "SELF_PAY":
        extra_tubes = max(0, panel["required_tube_count"] - 1)
        convenience = SELF_PAY_BASE_CONVENIENCE_CENTS + extra_tubes * SELF_PAY_PER_TUBE_CENTS
        waiver = min(convenience, redraw_count * SELF_PAY_REDRAW_WAIVER_UNIT_CENTS)
        total = max(0, fee + convenience - waiver)
    else:  # INSURANCE
        convenience = INSURANCE_FLAT_CONVENIENCE_CENTS
        waiver = min(convenience, redraw_count * INSURANCE_REDRAW_WAIVER_UNIT_CENTS)
        # Under insurance the patient total excludes the lab fee entirely.
        total = max(0, convenience - waiver)

    return fee, convenience, waiver, total


def order_total_due_estimate(order, panel, partner):
    """Forward-looking estimate stamped on LabOrder.total_due_cents (scaffold
    order_total_due_estimate). Uses the order's CURRENT redraw_count."""
    _, _, _, total = compute_billing(
        order["billing_mode"], panel, partner, order["priority"], order["redraw_count"]
    )
    return total
