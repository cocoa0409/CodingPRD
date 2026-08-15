"""License determination ladder, order total calculation, shipment fee."""

from decimal import Decimal, ROUND_HALF_UP

import db

GROUP_E = {"CUB", "IRN", "PRK", "SYR"}
DE_MINIMIS_GROUP_E = 10
DE_MINIMIS_DEFAULT = 25

TIER_BOUNDARY_CENTS = 100000
TIER_LOW_RATE = Decimal("0.02")
TIER_HIGH_RATE = Decimal("0.035")
FEE_RATE = Decimal("0.015")


def destination_embargoed(destination_country):
    """True when an ACTIVE EMBARGOED_COUNTRY entry with severity PROHIBITED
    covers the destination country."""
    return any(
        e["status"] == "ACTIVE"
        and e["list_source"] == "EMBARGOED_COUNTRY"
        and e["severity"] == "PROHIBITED"
        and e["country_code"] == destination_country
        for e in db.LIST_ENTRIES.values()
    )


def active_classification(product):
    if product["active_classification_id"] is None:
        return None
    return db.CLASSIFICATIONS.get(product["active_classification_id"])


def determine(product, party, destination_country, end_use):
    """Six-step license determination ladder. Callers guarantee the product
    has an ACTIVE classification."""
    if destination_embargoed(destination_country):
        return "PROHIBITED"
    if party["screening_posture"] == "BLOCKED":
        return "PROHIBITED"
    classification = active_classification(product)
    if classification["jurisdiction"] == "ITAR":
        return "LICENSE_REQUIRED"
    if end_use == "MILITARY":
        return "LICENSE_REQUIRED"
    if classification["classification_code"] == "EAR99":
        return "NOT_REQUIRED"
    threshold = DE_MINIMIS_GROUP_E if destination_country in GROUP_E else DE_MINIMIS_DEFAULT
    # Strictly greater than the threshold triggers LICENSE_REQUIRED; exactly
    # equal is NOT_REQUIRED.
    if product["controlled_content_pct"] > threshold:
        return "LICENSE_REQUIRED"
    return "NOT_REQUIRED"


def order_totals(quantity, unit_value_cents):
    """order_total_value: tier keyed ONLY on goods_value_cents; boundary 100000
    takes the high rate; surcharge rounded to whole cents round-half-up."""
    goods = quantity * unit_value_cents
    rate = TIER_LOW_RATE if goods < TIER_BOUNDARY_CENTS else TIER_HIGH_RATE
    surcharge = int((Decimal(goods) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return goods, surcharge, goods + surcharge


def shipment_fee(consumed_value_cents):
    """shipment_compliance_fee: per-shipment 1.5% fee, rounded individually."""
    return int(
        (Decimal(consumed_value_cents) * FEE_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
