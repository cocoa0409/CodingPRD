from decimal import Decimal, ROUND_HALF_UP

from db import db, base_fields
import domain


def base_charge(stored_vials):
    return stored_vials * domain.ANNUAL_RATE_CENTS_PER_VIAL


def renewal_amount(stored_vials, remaining_days):
    """Prorated cents = round_half_up(base * remaining_days / BILLING_PERIOD_DAYS)."""
    base = base_charge(stored_vials)
    amount = (Decimal(base) * Decimal(remaining_days) / Decimal(domain.BILLING_PERIOD_DAYS))
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def lapse_amount(stored_vials):
    return base_charge(stored_vials)


def issue_invoice(acct, period_index, billing_mode, remaining_days=None):
    if billing_mode == "RENEWAL":
        amount = renewal_amount(acct["stored_vials"], remaining_days)
    else:
        amount = lapse_amount(acct["stored_vials"])
    inv = base_fields(db)
    inv.update({
        "storage_account_id": acct["id"],
        "period_index": period_index,
        "billing_mode": billing_mode,
        "amount_cents": amount,
        "status": "ISSUED",
    })
    db.storage_invoices[inv["id"]] = inv
    return inv


def next_period_index(acct):
    existing = [iv["period_index"] for iv in db.storage_invoices.values()
                if iv["storage_account_id"] == acct["id"]]
    return (max(existing) + 1) if existing else 0
