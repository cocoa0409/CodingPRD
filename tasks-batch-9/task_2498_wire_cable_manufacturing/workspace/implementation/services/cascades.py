"""Multi-hop compliance cascades (PRD 2.7, 3.2, 3.3, 3.5).

Every hop runs inside the request that triggered it, processes sibling records
in ascending ``created_at`` order, is evaluated only against records the
previous hop actually moved, and never fails the request when a record does not
satisfy its own precondition.
"""

from db import db, sort_created, touch
from services import ledger

FROZEN_PROCESS_STATES = ("SHIPPED", "SCRAP_CLOSED")


# --------------------------------------------------------------------------
# Shared hops
# --------------------------------------------------------------------------
def _orders_for_products(products):
    out = []
    for product in products:
        rows = [
            o for o in db.customer_orders.values()
            if o["product_id"] == product["id"]
        ]
        out.extend(sort_created(rows))
    return out


def _lots_for_orders(orders):
    out = []
    for order in orders:
        rows = [
            l for l in db.production_lots.values()
            if l["order_id"] == order["id"]
        ]
        out.extend(sort_created(rows))
    return out


def _hold_orders(products, hold_reason):
    """Hop two of a suspension: place the commercial commitments on hold."""
    held = []
    for order in _orders_for_products(products):
        if order["fulfillment_status"] not in ("OPEN", "PARTIALLY_SHIPPED"):
            continue
        if order["pricing_status"] not in ("QUOTED", "LOCKED"):
            continue
        order["pricing_status"] = "HELD"
        order["hold_reason"] = hold_reason
        touch(order)
        held.append(order)
    return held


def _quarantine_lots(orders):
    """Hop three of a suspension: freeze the metal still on the floor."""
    frozen = []
    for lot in _lots_for_orders(orders):
        if lot["quality_state"] != "PENDING":
            continue
        if lot["process_state"] in FROZEN_PROCESS_STATES:
            continue
        lot["quality_state"] = "QUARANTINED"
        touch(lot)
        frozen.append(lot)
    return frozen


# --------------------------------------------------------------------------
# Compound suspension (PRD 3.2)
# --------------------------------------------------------------------------
def compound_suspended(compound):
    candidates = [
        p for p in db.catalog_products.values()
        if p["status"] == "RELEASED"
        and (
            p["insulation_compound_id"] == compound["id"]
            or p["jacket_compound_id"] == compound["id"]
        )
    ]
    suspended = []
    for product in sort_created(candidates):
        product["status"] = "SUSPENDED"
        touch(product)
        suspended.append(product)

    held = _hold_orders(suspended, "COMPOUND_SUSPENDED")
    _quarantine_lots(held)


# --------------------------------------------------------------------------
# Listing file suspension (PRD 3.3)
# --------------------------------------------------------------------------
def certification_suspended(cert):
    candidates = [
        p for p in db.catalog_products.values()
        if p["status"] == "RELEASED" and p["listing_certification_id"] == cert["id"]
    ]
    suspended = []
    for product in sort_created(candidates):
        product["status"] = "SUSPENDED"
        touch(product)
        suspended.append(product)

    held = _hold_orders(suspended, "CERTIFICATION_SUSPENDED")
    _quarantine_lots(held)


# --------------------------------------------------------------------------
# Listing file reinstatement (PRD 3.3) — the stale-pin rule
# --------------------------------------------------------------------------
def _pins_still_current(product):
    insulation = db.compounds.get(product["insulation_compound_id"])
    if insulation is None:
        return False
    if product["pinned_insulation_compound_version"] != insulation["version"]:
        return False
    if product["jacket_compound_id"] is None:
        return True
    jacket = db.compounds.get(product["jacket_compound_id"])
    if jacket is None:
        return False
    return product["pinned_jacket_compound_version"] == jacket["version"]


def certification_reinstated(cert):
    candidates = [
        p for p in db.catalog_products.values()
        if p["status"] == "SUSPENDED" and p["listing_certification_id"] == cert["id"]
    ]
    returned = []
    for product in sort_created(candidates):
        if _pins_still_current(product):
            product["status"] = "RELEASED"
            returned.append(product)
        else:
            # A compound re-qualified during the suspension window left the
            # print behind: the SKU is retired permanently.
            product["status"] = "OBSOLETE"
        touch(product)

    unheld = []
    for order in _orders_for_products(returned):
        if order["pricing_status"] != "HELD":
            continue
        order["pricing_status"] = "LOCKED"
        order["hold_reason"] = None
        touch(order)
        unheld.append(order)

    for lot in _lots_for_orders(unheld):
        if lot["quality_state"] != "QUARANTINED":
            continue
        lot["quality_state"] = "PENDING"
        touch(lot)


# --------------------------------------------------------------------------
# Order cancellation (PRD 3.5) — the compensating half of the mass ledger
# --------------------------------------------------------------------------
def order_cancelled(order):
    queued = [
        l for l in db.production_lots.values()
        if l["order_id"] == order["id"] and l["process_state"] == "QUEUED"
    ]
    for lot in sort_created(queued):
        # Nothing was ever drawn, so nothing is scrapped.
        lot["process_state"] = "SCRAP_CLOSED"
        touch(lot)
        rod_lot = db.rod_purchase_lots.get(lot["rod_lot_id"])
        if rod_lot is not None:
            ledger.release_mass(rod_lot, lot["consumed_rod_lbs"])


# --------------------------------------------------------------------------
# Lot scrap (PRD 3.7) — mass write-off, scrap alarm, sibling freeze
# --------------------------------------------------------------------------
def lot_scrapped(lot):
    rod_lot = db.rod_purchase_lots.get(lot["rod_lot_id"])
    if rod_lot is None:
        return
    quarantined = ledger.scrap_mass(rod_lot, lot["consumed_rod_lbs"])
    if quarantined:
        ledger.quarantine_sibling_lots(rod_lot, lot["id"])
