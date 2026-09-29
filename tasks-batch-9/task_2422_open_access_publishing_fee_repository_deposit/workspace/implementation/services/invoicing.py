"""invoice_expected_amount_validation and publisher_volume_discount_tier (PRD 3.7)."""
from decimal import Decimal

import constants as C
from db import db
from services.determination import effective_determination
from util import dec, fiscal_year_of, parse_iso_date, round_half_up

TA_ROUTES = ("TA_FULL", "TA_CAPPED")


def volume_discount_tier(invoice):
    """Prior PAID invoices of the same publisher in the same fiscal year only."""
    fiscal_year = fiscal_year_of(parse_iso_date(invoice["invoice_date"]))
    prior_paid_net_cents = 0
    for other in db.invoices.values():
        if other["publisher_id"] != invoice["publisher_id"]:
            continue
        if other["id"] == invoice["id"]:
            continue
        if other["status"] != "PAID":
            continue
        if fiscal_year_of(parse_iso_date(other["invoice_date"])) != fiscal_year:
            continue
        prior_paid_net_cents += other["net_cents"] or 0
    if prior_paid_net_cents >= C.TIER3_MIN_CENTS:
        return Decimal(C.TIER3_PCT)
    if prior_paid_net_cents >= C.TIER2_MIN_CENTS:
        return Decimal(C.TIER2_PCT)
    if prior_paid_net_cents >= C.TIER1_MIN_CENTS:
        return Decimal(C.TIER1_PCT)
    return Decimal("0")


def _as_json_number(value):
    """Render a Decimal fraction as a plain JSON number."""
    normalised = value.normalize()
    if normalised == normalised.to_integral_value():
        return int(normalised)
    return float(normalised)


def price_invoice(invoice):
    """Return the pricing fields; pinned rounding order (round each, then sum)."""
    determination = effective_determination(invoice["article_id"])
    base_cents = determination["list_base_cents"]

    if determination["route"] in TA_ROUTES:
        entitled = dec(determination["discount_pct_applied"])
    else:
        entitled = volume_discount_tier(invoice)

    net_cents = round_half_up(dec(base_cents) * (Decimal(1) - entitled))
    vat_cents = round_half_up(dec(net_cents) * dec(invoice["vat_pct"]))
    expected_amount_cents = net_cents + vat_cents
    variance_cents = invoice["invoice_amount_cents"] - expected_amount_cents

    claimed = dec(invoice["claimed_discount_pct"])
    if claimed < entitled - Decimal(C.DISCOUNT_EPSILON):
        outcome = "DISCOUNT_SHORTFALL"
    elif variance_cents == 0:
        outcome = "MATCH"
    elif abs(variance_cents) <= C.VARIANCE_TOLERANCE_CENTS:
        outcome = "WITHIN_TOLERANCE"
    else:
        outcome = "AMOUNT_VARIANCE"

    return {
        "entitled_discount_pct": _as_json_number(entitled),
        "net_cents": net_cents,
        "vat_cents": vat_cents,
        "expected_amount_cents": expected_amount_cents,
        "variance_cents": variance_cents,
        "validation_outcome": outcome,
    }
