"""The metal mass ledger (PRD 2.8) and the credit/deposit ledger (PRD 2.9)."""

import constants as C
from db import db, sort_created, touch
from util import D, money, rhu


# --------------------------------------------------------------------------
# Rod mass ledger
# --------------------------------------------------------------------------
def scrap_pct(rod_lot):
    return rhu(
        D("100") * D(rod_lot["scrapped_lbs"]) / D(rod_lot["purchase_weight_lbs"]), 2
    )


def commit_mass(rod_lot, amount):
    """Scheduling a lot: remaining -> committed.  Auto-CONSUMED at exactly zero."""
    rod_lot["remaining_lbs"] = money(D(rod_lot["remaining_lbs"]) - D(amount))
    rod_lot["committed_lbs"] = money(D(rod_lot["committed_lbs"]) + D(amount))
    touch(rod_lot)
    if rod_lot["remaining_lbs"] == money("0") and rod_lot["status"] == "RECEIVED":
        rod_lot["status"] = "CONSUMED"
        touch(rod_lot)


def scrap_mass(rod_lot, amount):
    """Scrapping a lot: committed -> scrapped.  Returns True when it quarantines."""
    rod_lot["committed_lbs"] = money(D(rod_lot["committed_lbs"]) - D(amount))
    rod_lot["scrapped_lbs"] = money(D(rod_lot["scrapped_lbs"]) + D(amount))
    touch(rod_lot)
    if rod_lot["status"] == "RECEIVED" and scrap_pct(rod_lot) > C.SCRAP_ALERT_PCT:
        rod_lot["status"] = "QUARANTINED"
        touch(rod_lot)
        return True
    return False


def release_mass(rod_lot, amount):
    """Cancelling a queued lot: committed -> remaining (never scrap)."""
    rod_lot["committed_lbs"] = money(D(rod_lot["committed_lbs"]) - D(amount))
    rod_lot["remaining_lbs"] = money(D(rod_lot["remaining_lbs"]) + D(amount))
    touch(rod_lot)


def quarantine_sibling_lots(rod_lot, exclude_lot_id):
    """Hop three of the scrap cascade: freeze every other PENDING lot on the heat."""
    siblings = [
        lot for lot in db.production_lots.values()
        if lot["rod_lot_id"] == rod_lot["id"]
        and lot["id"] != exclude_lot_id
        and lot["quality_state"] == "PENDING"
    ]
    for lot in sort_created(siblings):
        lot["quality_state"] = "QUARANTINED"
        touch(lot)


# --------------------------------------------------------------------------
# Credit and deposit ledger
# --------------------------------------------------------------------------
def _customer_open_ar(customer):
    total = D("0")
    for shipment in db.shipments.values():
        if shipment["status"] != "INVOICED":
            continue
        order = db.customer_orders.get(shipment["order_id"])
        if order is not None and order["customer_id"] == customer["id"]:
            total += D(shipment["invoice_amount_usd"] or 0)
    return money(total)


def _customer_deposit_balance(customer):
    total = D("0")
    for reel in db.reels.values():
        if reel["held_by_customer_id"] == customer["id"] and reel["status"] in (
            "SHIPPED",
            "RETURN_PENDING",
        ):
            total += D(reel["deposit_usd"])
    return money(total)


def recompute_credit(customer, bump_version=True):
    """customer_credit_exposure: refresh AR, deposits, exposure and standing."""
    customer["open_ar_usd"] = _customer_open_ar(customer)
    customer["reel_deposit_balance_usd"] = _customer_deposit_balance(customer)
    exposure = money(
        D(customer["open_ar_usd"])
        + D(customer["reel_deposit_balance_usd"])
        - D(customer["credit_memo_balance_usd"])
    )
    customer["credit_exposure_usd"] = exposure
    # Strictly greater than: exposure exactly on the limit stays ACTIVE.
    customer["status"] = (
        "CREDIT_HOLD" if exposure > D(customer["credit_limit_usd"]) else "ACTIVE"
    )
    if bump_version:
        touch(customer)
    return customer
