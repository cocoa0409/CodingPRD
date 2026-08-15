"""Cascade services: clock sweeps, order cancel release cascade, shipment
destroy resolution. All cascades are atomic within the triggering request and
every touched record takes its own updated_at refresh + version increment.
"""
from datetime import date, timedelta

from db import db
from services.calculations import (
    recompute_credit_used,
    reverse_accruals_for_order,
    run_backorder_waterfall,
    mint_backorder,
    order_lines,
    lazy_reset_quarterly_counter,
)
from util import CLOCK, touch


# ---------------------------------------------------------------------------
# Clock sweep (PRD 2.4): runs on every POST /vet/_clock/set_current_utc.
#   1. Authorizations APPROVED with valid_until < new date -> EXPIRED
#   2. Lots with expiry_date < new date -> EXPIRED (+ release cascade)
#   3. ShortDateCredits APPROVED with approval date > 30 days in the past
#      -> EXPIRED
# Boundary: a lot expiring exactly on the new date survives; an authorization
# whose valid_until equals the new date survives.
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    today = CLOCK.today()

    for auth in db["manufacturer_authorizations"].values():
        if auth["status"] == "APPROVED" and auth["valid_until"] < today:
            auth["status"] = "EXPIRED"
            touch(auth)

    for lot in list(db["inventory_lots"].values()):
        if lot["status"] in ("AVAILABLE", "DEPLETED") and lot["expiry_date"] < today:
            _expire_lot(lot)

    for credit in db["short_date_credits"].values():
        if credit["status"] != "APPROVED":
            continue
        approved_on = credit.get("approved_on")
        if approved_on is None:
            continue
        if today > approved_on + timedelta(days=30):
            credit["status"] = "EXPIRED"
            touch(credit)


def _expire_lot(lot):
    """Lot -> EXPIRED with the release cascade (PRD 3.6 mirror-image):
    every ALLOCATED line holding this lot reverts to BACKORDERED (qty zeroed,
    lot cleared), a fresh BackorderLine minted per line, lot.qty_allocated := 0,
    each affected order APPROVED -> BACKORDERED."""
    lot["status"] = "EXPIRED"
    lot["qty_available"] = lot["qty_on_hand"] - lot["qty_allocated"]

    affected_orders = set()
    for line in db["order_lines"].values():
        if line["lot_id"] == lot["id"] and line["status"] == "ALLOCATED":
            line["qty_allocated"] = 0
            line["lot_id"] = None
            line["status"] = "BACKORDERED"
            touch(line)
            mint_backorder(line)
            affected_orders.add(line["order_id"])

    lot["qty_allocated"] = 0
    lot["qty_available"] = lot["qty_on_hand"]
    touch(lot)

    for oid in affected_orders:
        order = db["orders"].get(oid)
        if order is not None and order["status"] == "APPROVED":
            order["status"] = "BACKORDERED"
            touch(order)
            recompute_credit_used(order["clinic_id"])


# ---------------------------------------------------------------------------
# Order cancellation (PRD 3.6). Blast radius by source state:
#   DRAFT: cancel PENDING lines only.
#   SUBMITTED: cancel PENDING lines + release the reserved window.
#   APPROVED / BACKORDERED: full release cascade (lots, waterfall, own OPEN
#   backorders, accruals, quarterly counters, credit).
# ---------------------------------------------------------------------------

def cancel_order_cascade(order, lines=None):
    if lines is None:
        lines = order_lines(order["id"])
    src = order["status"]

    if src in ("APPROVED", "BACKORDERED"):
        released_products = set()
        # (1) release ALLOCATED lines
        for line in lines:
            if line["status"] == "ALLOCATED":
                lot = db["inventory_lots"].get(line["lot_id"]) if line["lot_id"] else None
                if lot is not None:
                    lot["qty_allocated"] -= line["qty_requested"]
                    # DEPLETED -> AVAILABLE when availability returns
                    lot["qty_available"] = lot["qty_on_hand"] - lot["qty_allocated"]
                    if lot["status"] == "DEPLETED" and lot["qty_available"] > 0:
                        lot["status"] = "AVAILABLE"
                    touch(lot)
                    released_products.add(lot["product_id"])
                line["qty_allocated"] = 0
                line["lot_id"] = None
                line["status"] = "CANCELLED"
                touch(line)
            elif line["status"] == "BACKORDERED":
                line["status"] = "CANCELLED"
                touch(line)
            elif line["status"] == "PENDING":
                line["status"] = "CANCELLED"
                touch(line)

        # (2) own still-OPEN backorders -> CANCELLED
        line_ids = {l["id"] for l in lines}
        for bo in db["backorder_lines"].values():
            if bo["order_line_id"] in line_ids and bo["status"] == "OPEN":
                bo["status"] = "CANCELLED"
                touch(bo)

        # (3) freed availability runs the waterfall per product
        for pid in released_products:
            run_backorder_waterfall(pid)

        # (4) PROVISIONAL accruals reversed + enrollment QTD decremented
        reverse_accruals_for_order(order)

        # (5) decrement quarterly counters for this order's Rx units
        _decrement_quarterly_counters(order, lines)

    else:
        for line in lines:
            if line["status"] == "PENDING":
                line["status"] = "CANCELLED"
                touch(line)

    order["status"] = "CANCELLED"
    touch(order)
    recompute_credit_used(order["clinic_id"])


def _rx_units_by_manufacturer(order, lines):
    """qty_requested of RX_PHARMACEUTICAL lines grouped by manufacturer_code."""
    out = {}
    for line in lines:
        prod = db["products"].get(line["product_id"])
        if prod is None or prod["product_type"] != "RX_PHARMACEUTICAL":
            continue
        out[prod["manufacturer_code"]] = out.get(prod["manufacturer_code"], 0) + line["qty_requested"]
    return out


def _decrement_quarterly_counters(order, lines):
    for mfr, qty in _rx_units_by_manufacturer(order, lines).items():
        auth = find_covering_authorization(order["clinic_id"], mfr, any_status=True)
        if auth is not None:
            lazy_reset_quarterly_counter(auth)
            auth["quantity_approved_this_quarter"] = max(
                0, auth["quantity_approved_this_quarter"] - qty)
            touch(auth)


def increment_quarterly_counters(order, lines):
    from services.calculations import lazy_reset_quarterly_counter as _lz
    for mfr, qty in _rx_units_by_manufacturer(order, lines).items():
        auth = find_covering_authorization(order["clinic_id"], mfr)
        if auth is not None:
            _lz(auth)
            auth["quantity_approved_this_quarter"] += qty
            touch(auth)


def find_covering_authorization(clinic_id, manufacturer_code, any_status=False):
    """The authorization for (clinic, manufacturer). For cap bookkeeping we use
    the APPROVED window-covering one; with any_status=True, the most recent
    non-terminal one covering today if any (fallback for decrement paths)."""
    today = CLOCK.today()
    best = None
    for auth in db["manufacturer_authorizations"].values():
        if auth["clinic_id"] != clinic_id or auth["manufacturer_code"] != manufacturer_code:
            continue
        if any_status:
            if auth["status"] in ("PENDING", "APPROVED", "SUSPENDED"):
                if best is None or auth["created_at"] > best["created_at"]:
                    best = auth
        else:
            if (auth["status"] == "APPROVED"
                    and auth["valid_from"] <= today <= auth["valid_until"]):
                if best is None or auth["created_at"] > best["created_at"]:
                    best = auth
    return best


# ---------------------------------------------------------------------------
# Backorder cancel recompute (PRD 3.6): if no line remains BACKORDERED and at
# least one is ALLOCATED -> APPROVED; if every line CANCELLED -> CANCELLED
# (window released, credit recomputed).
# ---------------------------------------------------------------------------

def recompute_order_after_backorder_cancel(order):
    lines = order_lines(order["id"])
    if all(l["status"] == "CANCELLED" for l in lines):
        order["status"] = "CANCELLED"
        touch(order)
        recompute_credit_used(order["clinic_id"])
        return
    if order["status"] == "BACKORDERED":
        if not any(l["status"] == "BACKORDERED" for l in lines) and \
           any(l["status"] == "ALLOCATED" for l in lines):
            order["status"] = "APPROVED"
            touch(order)
            recompute_credit_used(order["clinic_id"])
