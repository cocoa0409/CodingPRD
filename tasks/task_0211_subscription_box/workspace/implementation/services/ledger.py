"""Invoice / WalletEntry / BillingCycle creation helpers + cadence math."""
from datetime import timedelta

from db import db
from common import new_record
from services.calculations import recompute_wallet_balance


def cadence_delta(cadence):
    """Cadence period length (PRD: MONTHLY/QUARTERLY).

    A month is modeled as 30 days, a quarter as 90 days, so renewal arithmetic
    is deterministic for test-driving via the simulated clock.
    """
    if cadence == "MONTHLY":
        return timedelta(days=30)
    if cadence == "QUARTERLY":
        return timedelta(days=90)
    return timedelta(days=30)


def create_invoice(subscriber_id, subscription_id, gross_amount_cents, kind, status="SETTLED"):
    inv = new_record({
        "subscriber_id": subscriber_id,
        "subscription_id": subscription_id,
        "gross_amount_cents": gross_amount_cents,
        "kind": kind,
        "status": status,
    })
    db.invoices[inv["id"]] = inv
    return inv


def create_wallet_entry(subscriber_id, amount_cents, kind, source_ref_id=None):
    """WalletEntry is append-only: only id + created_at (PRD §2.4)."""
    ts = db.now()
    entry = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
        "subscriber_id": subscriber_id,
        "amount_cents": amount_cents,
        "kind": kind,
        "source_ref_id": source_ref_id,
    }
    db.wallet_entries[entry["id"]] = entry
    recompute_wallet_balance(subscriber_id)
    return entry


def create_billing_cycle(subscription_id, period_index, amount_charged_cents,
                         funding_source, status="PENDING", charged_at=None):
    cycle = new_record({
        "subscription_id": subscription_id,
        "period_index": period_index,
        "amount_charged_cents": amount_charged_cents,
        "funding_source": funding_source,
        "status": status,
        "charged_at": charged_at,
    })
    db.billing_cycles[cycle["id"]] = cycle
    return cycle
