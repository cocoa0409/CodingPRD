"""reserve_provision (PRD 2.11) and the append-only reserve ledger.

The reserve is always recomputed from scratch over the carrier's invoice
population; it is never adjusted incrementally.
"""
from decimal import Decimal

from constants import (DISPUTE_LOSS_PROBABILITY_PCT, TIER_1_PCT, TIER_2_FLOOR_USD,
                       TIER_2_PCT, TIER_3_FLOOR_USD, TIER_3_PCT)
from dec import ZERO, q2
from store import base_record, db, touch

HUNDRED = Decimal("100")
ZERO2 = Decimal("0.00")


def tier_pct_for(net_receivable_usd):
    if net_receivable_usd <= ZERO:
        return ZERO2
    if net_receivable_usd < TIER_2_FLOOR_USD:
        return TIER_1_PCT
    if net_receivable_usd < TIER_3_FLOOR_USD:
        return TIER_2_PCT
    return TIER_3_PCT


def carrier_invoices(carrier_id):
    return [i for i in db.invoices.values() if i["carrier_id"] == carrier_id]


def compute_figures(carrier):
    """Steps 1 to 3 of reserve_provision."""
    open_receivable = ZERO2
    disputed_receivable = ZERO2
    for invoice in carrier_invoices(carrier["id"]):
        if invoice["lifecycle_status"] == "ISSUED":
            if invoice["payment_status"] in ("UNPAID", "PARTIALLY_PAID"):
                open_receivable += invoice["open_balance_usd"]
            disputed_receivable += invoice["disputed_amount_usd"]
    open_receivable = q2(open_receivable)
    disputed_receivable = q2(disputed_receivable)
    net_receivable = q2(open_receivable - disputed_receivable)
    tier_pct = tier_pct_for(net_receivable)
    base = net_receivable if net_receivable > ZERO else ZERO2
    uncollectible = q2(base * tier_pct / HUNDRED)
    regulatory_disputed = disputed_receivable
    gaap_disputed = q2(disputed_receivable * DISPUTE_LOSS_PROBABILITY_PCT / HUNDRED)
    return {
        "open_receivable_usd": open_receivable,
        "disputed_receivable_usd": disputed_receivable,
        "net_receivable_usd": net_receivable,
        "tier_pct": tier_pct,
        "uncollectible_reserve_balance_usd": uncollectible,
        "regulatory_disputed_reserve_usd": regulatory_disputed,
        "gaap_disputed_reserve_usd": gaap_disputed,
        "disputed_reserve_basis_delta_usd": q2(regulatory_disputed - gaap_disputed),
    }


def append_entry(carrier, invoice_id, reserve_bucket, entry_type, amount_usd,
                 balance_after_usd, source_event):
    entry = base_record(with_version=False)
    entry.update({
        "carrier_id": carrier["id"],
        "invoice_id": invoice_id,
        "reserve_bucket": reserve_bucket,
        "entry_type": entry_type,
        "amount_usd": q2(amount_usd),
        "balance_after_usd": q2(balance_after_usd),
        "source_event": source_event,
    })
    db.ledger_entries[entry["id"]] = entry
    return entry


def recompute(carrier, source_event, invoice_id=None, write_off_amount_usd=None,
              bump_version=True):
    """Recompute the carrier's reserve figures and append one ledger entry per
    bucket whose balance actually moved."""
    old_uncollectible = carrier["uncollectible_reserve_balance_usd"]
    old_disputed = carrier["disputed_reserve_balance_usd"]

    figures = compute_figures(carrier)
    new_uncollectible = figures["uncollectible_reserve_balance_usd"]
    new_disputed = figures["regulatory_disputed_reserve_usd"]

    carrier["open_receivable_usd"] = figures["open_receivable_usd"]
    carrier["disputed_receivable_usd"] = figures["disputed_receivable_usd"]
    carrier["net_receivable_usd"] = figures["net_receivable_usd"]
    carrier["uncollectible_reserve_balance_usd"] = new_uncollectible
    carrier["disputed_reserve_balance_usd"] = new_disputed
    if bump_version:
        touch(carrier)

    entries = []
    if write_off_amount_usd is not None:
        entries.append(append_entry(
            carrier, invoice_id, "UNCOLLECTIBLE", "WRITE_OFF",
            write_off_amount_usd, old_uncollectible, source_event))

    if new_disputed != old_disputed:
        delta = q2(new_disputed - old_disputed)
        entry_type = "DISPUTE_PROVISION" if delta > ZERO else "DISPUTE_RELEASE"
        entries.append(append_entry(
            carrier, invoice_id, "DISPUTED_REVENUE", entry_type, delta,
            new_disputed, source_event))

    if new_uncollectible != old_uncollectible:
        delta = q2(new_uncollectible - old_uncollectible)
        entries.append(append_entry(
            carrier, invoice_id, "UNCOLLECTIBLE", "UNCOLLECTIBLE_ADJUSTMENT",
            delta, new_uncollectible, source_event))

    return entries
