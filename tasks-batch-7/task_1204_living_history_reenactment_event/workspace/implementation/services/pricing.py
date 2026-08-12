"""Calculation rules from the scaffold §1.3, implemented with Decimal math."""

from decimal import Decimal

from util import round_half_up

_LINE_PRICE_FIELD = {
    "ADULT_DAY": "adult_day_price_cents",
    "CHILD_DAY": "child_day_price_cents",
    "ADULT_WEEKEND": "adult_weekend_price_cents",
    "CHILD_WEEKEND": "child_weekend_price_cents",
}
LINE_TYPES = set(_LINE_PRICE_FIELD.keys())


def ticket_total_cents(event, lines, pricing_ts):
    """ticket_order_pricing: per-line round-half-up, then sum, then + service fee.

    pricing_ts is created_at for the provisional quote, paid_at for the charge.
    Early-bird eligibility is inclusive: pricing_ts <= cutoff.
    """
    eligible = pricing_ts <= event["early_bird_cutoff_at"]
    total = 0
    for line in lines:
        unit = event[_LINE_PRICE_FIELD[line["line_type"]]]
        line_cents = Decimal(unit * line["quantity"])
        if eligible:
            line_cents = line_cents * (Decimal(1) - Decimal(str(event["early_bird_pct"])))
        total += round_half_up(line_cents)
    return total + event["service_fee_cents"]


def refund_amounts(event, order, reason):
    """ticket_refund_amount -> (refund_amount_cents, retained_fee_cents)."""
    final = order["final_total_cents"]
    if reason == "PATRON_CHOICE":
        retained = round_half_up(Decimal(final) * Decimal(str(event["refund_retain_pct"])))
        return final - retained, retained
    # EVENT_CONTINGENCY: retain 0; pro-rate unused days to cancelled_at.
    total_days = (event["event_ends_at"].date() - event["event_starts_at"].date()).days + 1
    elapsed = (event["cancelled_at"].date() - event["event_starts_at"].date()).days
    elapsed = max(0, min(elapsed, total_days))
    refund = round_half_up(
        Decimal(final * (total_days - elapsed)) / Decimal(total_days)
    )
    return refund, 0


def vendor_booth_fee(event, vendor, final_variant=False):
    """vendor_booth_fee; the late-insurance surcharge applies to the final variant only."""
    base = (
        vendor["frontage_feet"]
        * vendor["requested_days"]
        * event["vendor_frontage_rate_cents"]
    )
    if vendor["requested_days"] >= 3:
        base = round_half_up(
            Decimal(base) * (Decimal(1) - Decimal(str(event["vendor_multi_day_discount_pct"])))
        )
    fee = max(base, event["vendor_min_fee_cents"])
    if final_variant and vendor["insurance_uploaded_at"] > event["vendor_insurance_deadline_at"]:
        fee += event["vendor_late_insurance_surcharge_cents"]
    return fee


def parking_units_used(vehicle_class):
    return 2 if vehicle_class == "OVERSIZE" else 1
