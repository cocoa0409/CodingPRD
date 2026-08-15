"""Stock reservation waterfall + cold-chain capacity gate
(SCAFFOLD calculations.stock_reservation_waterfall, PRD §3.5).

Waterfall order: candidates with free qty (on_hand - reserved) > 0, walked
oldest-first by created_at ASC, tie-break lot_code ASC (never id). Cold-chain
lines draw ONLY from COLD_STORE lots. Per COLD_STORE lot, the sum of reserved
allocations whose half-open [accepted_at, reservation_window_end) window
overlaps the new order's window, plus the new allocation, must not exceed
capacity_qty. Windows that merely touch (end == start) do NOT overlap.
"""
import db
from db import _parse_iso
from errors import err_stock_insufficient, err_cold_chain_capacity_exceeded


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def _active_cold_reserved_on_lot(lot_id, new_window_start, new_window_end):
    """Sum of reserved allocations on this lot from non-terminal orders whose
    reservation windows overlap the new order's window."""
    total = 0
    for order in db.orders.values():
        if order.get("fulfillment_status") not in ("OPEN", "PARTIALLY_DELIVERED"):
            continue
        o_start = _parse_iso(order.get("accepted_at"))
        o_end = _parse_iso(order.get("reservation_window_end"))
        if o_start is None or o_end is None:
            continue
        if not _windows_overlap(o_start, o_end, new_window_start, new_window_end):
            continue
        for line in order.get("lines", []):
            for alloc in line.get("allocations", []):
                if alloc.get("stock_lot_id") == lot_id:
                    total += alloc.get("qty", 0)
    return total


def run_waterfall(order_lines, window_start_dt, window_end_dt):
    """Simulate (then commit) allocation. Returns list of allocations per line:
    [{catalog_item_id, allocations: [{stock_lot_id, qty}]}].

    Atomicity: checks ALL preconditions before committing ANY change — if any
    line cannot be fully allocated (ERR_STOCK_INSUFFICIENT) or any COLD_STORE
    lot capacity would be exceeded (ERR_COLD_CHAIN_CAPACITY_EXCEEDED), no
    partial reservation persists.
    """
    # planned allocations: lot_id -> qty (for capacity accounting within this order)
    planned_by_lot = {}
    result = []

    for line in order_lines:
        item = db.catalog_items.get(line["catalog_item_id"])
        cold = bool(item.get("requires_cold_chain")) if item else False
        remaining = line["qty"]
        allocations = []

        candidates = []
        for lot in db.stock_lots.values():
            if lot["catalog_item_id"] != line["catalog_item_id"]:
                continue
            if cold and lot["storage_tier"] != "COLD_STORE":
                continue  # cold items may only draw from COLD_STORE lots
            free = lot["on_hand_qty"] - lot["reserved_qty"] - planned_by_lot.get(lot["id"], 0)
            if free <= 0:
                continue
            candidates.append((lot, free))
        candidates.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["lot_code"]))

        for lot, free in candidates:
            if remaining <= 0:
                break
            take = min(remaining, free)
            if take <= 0:
                continue
            allocations.append({"stock_lot_id": lot["id"], "qty": take})
            planned_by_lot[lot["id"]] = planned_by_lot.get(lot["id"], 0) + take
            remaining -= take

        if remaining > 0:
            raise err_stock_insufficient()
        result.append({"catalog_item_id": line["catalog_item_id"],
                       "allocations": allocations})

    # Cold-chain aggregate capacity gate per COLD_STORE lot (checked AFTER
    # stock sufficiency so ERR_STOCK_INSUFFICIENT masks a capacity failure,
    # matching the accept ordering: stock first, then cold-chain capacity).
    for lot_id, new_alloc in planned_by_lot.items():
        lot = db.stock_lots[lot_id]
        if lot["storage_tier"] != "COLD_STORE":
            continue
        overlapping = _active_cold_reserved_on_lot(lot_id, window_start_dt, window_end_dt)
        if overlapping + new_alloc > lot["capacity_qty"]:
            raise err_cold_chain_capacity_exceeded()

    # Commit: move on_hand -> reserved on each contributing lot.
    for lot_id, qty in planned_by_lot.items():
        lot = db.stock_lots[lot_id]
        lot["on_hand_qty"] -= qty
        lot["reserved_qty"] += qty
        db.touch(lot)

    return result


def release_allocations(order):
    """Release an order's outstanding reservations back to on_hand.

    Allocation records shrink as confirmations deduct delivered quantities
    (deduct_confirmed), so each allocation's current qty is exactly the
    still-reserved, undelivered remainder. Releasing it therefore covers both
    the full-release case (order cancel, where nothing was confirmed) and the
    remainder-release case (vessel depart on a PARTIALLY_DELIVERED order).
    """
    for line in order.get("lines", []):
        for alloc in line.get("allocations", []):
            release_qty = alloc["qty"]
            if release_qty <= 0:
                continue
            lot = db.stock_lots.get(alloc["stock_lot_id"])
            if lot is None:
                continue
            lot["reserved_qty"] -= release_qty
            lot["on_hand_qty"] += release_qty
            db.touch(lot)
            alloc["qty"] = 0


def deduct_confirmed(order_line, confirmed_qty):
    """On delivery confirm: reserved_qty -= confirmed, on_hand_qty -= confirmed
    per allocated lot (SCAFFOLD Order transition side effect hop 1b)."""
    remaining = confirmed_qty
    for alloc in order_line.get("allocations", []):
        if remaining <= 0:
            break
        take = min(alloc["qty"], remaining)
        if take <= 0:
            continue
        lot = db.stock_lots.get(alloc["stock_lot_id"])
        if lot is not None:
            lot["reserved_qty"] -= take
            lot["on_hand_qty"] -= take
            db.touch(lot)
        alloc["qty"] -= take
        remaining -= take
