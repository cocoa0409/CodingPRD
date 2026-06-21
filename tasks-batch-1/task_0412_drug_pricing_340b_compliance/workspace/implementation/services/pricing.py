"""Ceiling-price calculations. PRD §3.3, scaffold §1.3 ceiling_price &
published_vs_provisional_ceiling."""
from db import db

PENNY_PRICE_CENTS = 1


def compute_ceiling(amp_per_unit_cents, ura_per_unit_cents):
    """Return (ceiling_price_per_unit_cents, pricing_variant).

    Inclusive penny boundary: ura >= amp -> PENNY (1 cent), else STANDARD.
    """
    if ura_per_unit_cents >= amp_per_unit_cents:
        return PENNY_PRICE_CENTS, "PENNY"
    return amp_per_unit_cents - ura_per_unit_cents, "STANDARD"


def ceiling_records_for(drug_product_id, quarter):
    return [
        c
        for c in db.ceiling_prices.all()
        if c["drug_product_id"] == drug_product_id and c["quarter"] == quarter
    ]


def effective_ceiling(drug_product_id, quarter):
    """Select the effective ceiling record for (drug_product_id, quarter).

    Returns (record, variant) where variant in {FINAL, PROVISIONAL}, or
    (None, None) when no record exists.

    Published wins over provisional; within a tier, most-recently-created by
    created_at (tie-break: insertion sequence). PRD §3.3.
    """
    candidates = ceiling_records_for(drug_product_id, quarter)
    published = [c for c in candidates if c["is_published"]]
    if published:
        eff = max(published, key=lambda c: c["_seq"])
        return eff, "FINAL"
    if candidates:
        provisional = [c for c in candidates if not c["is_published"]]
        eff = max(provisional, key=lambda c: c["_seq"])
        return eff, "PROVISIONAL"
    return None, None


def effective_published_ceiling(drug_product_id, quarter):
    """Most-recently-created published ceiling record, or None. Used for
    reconciliation and repayment assessment (FINAL only)."""
    published = [
        c for c in ceiling_records_for(drug_product_id, quarter) if c["is_published"]
    ]
    if not published:
        return None
    return max(published, key=lambda c: c["_seq"])
