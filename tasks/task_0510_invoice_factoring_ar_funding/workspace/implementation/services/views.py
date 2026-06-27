"""Serialisation views that recompute live/derived fields on read."""

import db
from common import public
from services import calc


def invoice_view(invoice):
    """Return a public copy with computed fields recomputed for the response.

    Recomputes: amount_collected_cents, dilution_cents, aging_bucket, and
    accrued_fee_cents (PROVISIONAL while FUNDED/OUTSTANDING).
    """
    inv = dict(invoice)
    inv["amount_collected_cents"] = calc.amount_collected(invoice["id"])
    inv["dilution_cents"] = calc.dilution_cents(invoice["id"])
    inv["aging_bucket"] = calc.aging_bucket(invoice)
    if invoice["status"] in ("FUNDED", "OUTSTANDING"):
        inv["accrued_fee_cents"] = calc.provisional_fee(invoice)
    else:
        inv["accrued_fee_cents"] = invoice.get("accrued_fee_cents", 0)
    return public(inv)


def client_view(client):
    """Recompute denormalized balances on read and return the public copy."""
    from services import ledger
    ledger.recompute_client_balances(client)
    return public(client)


def debtor_view(debtor):
    from services import ledger
    ledger.recompute_debtor_balance(debtor)
    return public(debtor)
