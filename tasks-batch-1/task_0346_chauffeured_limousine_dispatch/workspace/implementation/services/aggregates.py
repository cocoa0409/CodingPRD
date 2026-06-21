"""Computed aggregate recomputation (PRD §2.9)."""
import db
from db import touch


def recompute_outstanding_balance(account_id):
    """CorporateAccount.outstanding_balance_cents (PRD §2.9 / §3.8).

    Sum of final_total_cents over this account's reservations whose
    settlement_status is INVOICED (amounts that moved to SETTLED/WRITTEN_OFF
    are excluded). Mutating the aggregate bumps version + updated_at.
    """
    account = db.corporate_accounts.get(account_id)
    if account is None:
        return
    total = 0
    for res in db.reservations.values():
        if res["corporate_account_id"] != account_id:
            continue
        if res["settlement_status"] != "INVOICED":
            continue
        amount = res.get("final_total_cents")
        if amount is None:
            amount = res.get("cancellation_fee_cents") or 0
        total += amount
    account["outstanding_balance_cents"] = total
    touch(account)


def recompute_open_farmouts(affiliate_id):
    """Affiliate.open_farmouts (PRD §2.9 / §3.5).

    Count of this affiliate's farm-out orders whose status is OFFERED or ACCEPTED.
    """
    affiliate = db.affiliates.get(affiliate_id)
    if affiliate is None:
        return
    count = 0
    for fo in db.farm_out_orders.values():
        if fo["affiliate_id"] != affiliate_id:
            continue
        if fo["status"] in ("OFFERED", "ACCEPTED"):
            count += 1
    affiliate["open_farmouts"] = count
    touch(affiliate)
