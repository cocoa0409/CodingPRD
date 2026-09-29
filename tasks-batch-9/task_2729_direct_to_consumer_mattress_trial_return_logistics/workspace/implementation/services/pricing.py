"""The four-way refund ledger, in both variants."""
from services import calc, entities


def price_return_case(case, order, model, bundle):
    """Both variants of refund_settlement from the current inspection findings.

    gross_refundable_cents is always the order's paid_amount_cents. The two
    deductions that do not depend on the variant (bundle unwind and damage
    offset) are computed once and shared.
    """
    gross = order["paid_amount_cents"]
    trial_nights = model["trial_nights"]
    nights_used = case["nights_used"] or 0
    unwind = calc.bundle_unwind(
        bundle,
        order["gross_price_cents"],
        order["bundle_discount_cents"],
        nights_used,
        trial_nights,
        case["accessory_returned"],
    )
    damage = calc.damage_offset(
        order["paid_amount_cents"], case["condition_grade"], case["soil_flag"])
    provisional_proration = calc.proration_provisional(
        gross, nights_used, trial_nights)
    final_proration = calc.proration_final(gross, nights_used)
    return {
        "gross_refundable_cents": gross,
        "bundle_unwind_cents": unwind,
        "damage_offset_cents": damage,
        "provisional_proration_cents": provisional_proration,
        "final_proration_cents": final_proration,
        "provisional_refund_cents": gross - provisional_proration - unwind
        - damage,
        "final_refund_cents": gross - final_proration - unwind - damage,
    }


def priced_context(case):
    """Returns (order, model, bundle) for a case, or None when the case has not
    been inspected and therefore cannot be priced."""
    order = entities.get_order(case["order_id"])
    model = entities.model_of_order(order)
    bundle = entities.bundle_of_order(order)
    return order, model, bundle
