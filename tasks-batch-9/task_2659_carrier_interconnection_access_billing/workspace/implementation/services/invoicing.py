"""Invoice dimension bookkeeping (PRD 2.10 and 3.8)."""
from decimal import Decimal

from constants import DISPUTE_OPEN_STATUSES
from dec import q2
from store import db, ordered

ZERO2 = Decimal("0.00")


def invoice_disputes(invoice_id):
    return ordered([d for d in db.disputes.values() if d["invoice_id"] == invoice_id])


def recompute_open_balance(invoice):
    invoice["open_balance_usd"] = q2(invoice["billed_amount_usd"]
                                     - invoice["credited_amount_usd"]
                                     - invoice["paid_amount_usd"])
    return invoice["open_balance_usd"]


def apply_credit(invoice, amount_usd):
    invoice["credited_amount_usd"] = q2(invoice["credited_amount_usd"] + amount_usd)
    recompute_open_balance(invoice)
    if (invoice["open_balance_usd"] <= ZERO2
            and invoice["payment_status"] in ("UNPAID", "PARTIALLY_PAID")):
        invoice["payment_status"] = "PAID"
    return invoice


def refresh_dispute_dimension(invoice):
    disputes = invoice_disputes(invoice["id"])
    total = ZERO2
    open_found = False
    for dispute in disputes:
        if dispute["status"] in DISPUTE_OPEN_STATUSES:
            open_found = True
            total += dispute["disputed_amount_usd"]
    invoice["disputed_amount_usd"] = q2(total)
    if open_found:
        invoice["dispute_status"] = "DISPUTED"
    elif disputes:
        invoice["dispute_status"] = "RESOLVED"
    else:
        invoice["dispute_status"] = "NONE"
    return invoice


def derive_lifecycle(invoice):
    """Once ISSUED, an invoice closes as soon as it is fully settled and no
    dispute is outstanding."""
    if (invoice["lifecycle_status"] == "ISSUED"
            and invoice["payment_status"] in ("PAID", "WRITTEN_OFF")
            and invoice["dispute_status"] in ("NONE", "RESOLVED")):
        invoice["lifecycle_status"] = "CLOSED"
        return True
    return False
