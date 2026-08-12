"""The warranty pin of PRD 3.3, shared by device claiming and order fulfilment."""

from timeutil import add_months_to_date, midnight_utc, render_instant, try_parse_date


def pin_warranty(catalog_entry, subscription, plan, purchase_date_str):
    """Return (warranty_expires_at, warranty_basis).

    The base term is the catalog entry's base_warranty_months.  The extension
    applies only when the subscription is ACTIVE or PAST_DUE and the in-force
    plan's warranty_extension_months is strictly greater than 0.  The expiry
    is midnight UTC of purchase_date plus the whole number of months, clamped
    to the last day of the target month, rendered by the single server
    renderer and therefore always at 00:00:00.000Z.
    """
    base_months = catalog_entry["base_warranty_months"]
    extension = plan["warranty_extension_months"] if plan is not None else 0
    status = subscription.get("status") if subscription is not None else None
    if status in ("ACTIVE", "PAST_DUE") and extension > 0:
        total_months = base_months + extension
        basis = "TIER_EXTENDED"
    else:
        total_months = base_months
        basis = "BASE_ONLY"
    ymd = try_parse_date(purchase_date_str)
    expires = midnight_utc(add_months_to_date(ymd, total_months))
    return render_instant(expires), basis
