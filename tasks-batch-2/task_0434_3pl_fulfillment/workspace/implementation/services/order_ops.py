"""Order workflow helpers: FEFO reservation, pick-task generation, consumption,
cartonization, handling billing, and wave auto-completion (PRD §3.4-§3.8)."""
from db import store, new_id, stamp_create, touch
from errors import err
import calc

TERMINAL_ORDER_STATES = {"SHIPPED", "CANCELLED", "SHORT"}


def order_total_units(order):
    return sum(line["qty"] for line in order["lines"])


def lots_for_client_sku(client_id, sku_id):
    """Eligible lots for a client's SKU, ordered FEFO by created_at ASC.

    The lot's own id is never used as a selector/tiebreak; _seq (insertion order)
    breaks created_at ties deterministically (PRD §3.4).
    """
    lots = [
        l for l in store.inventory_lots.values()
        if l["client_id"] == client_id and l["sku_id"] == sku_id
    ]
    return sorted(lots, key=lambda l: (l["created_at"], l["_seq"]))


def available_for_client_sku(client_id, sku_id):
    return sum(
        (l["on_hand_qty"] - l["reserved_qty"])
        for l in store.inventory_lots.values()
        if l["client_id"] == client_id and l["sku_id"] == sku_id
    )


def check_coverage(order):
    """True if every line's qty is coverable by available across the client's lots.

    Lines for the same SKU draw from a shared pool, so we accumulate per SKU.
    """
    needed = {}
    for line in order["lines"]:
        needed[line["sku_id"]] = needed.get(line["sku_id"], 0) + line["qty"]
    for sku_id, qty in needed.items():
        if available_for_client_sku(order["client_id"], sku_id) < qty:
            return False
    return True


def reserve_order(order):
    """Reserve every line FEFO and create ASSIGNED PickTasks (PRD §3.4).

    Caller has already verified coverage atomically across all member orders.
    Reservation draws from FEFO lots; a single line may span multiple lots.
    """
    for line in order["lines"]:
        remaining = line["qty"]
        for lot in lots_for_client_sku(order["client_id"], line["sku_id"]):
            if remaining <= 0:
                break
            avail = lot["on_hand_qty"] - lot["reserved_qty"]
            if avail <= 0:
                continue
            take = min(avail, remaining)
            lot["reserved_qty"] += take
            touch(lot)
            touch_bin_for_lot(lot)
            pt = stamp_create({
                "id": new_id(),
                "order_id": order["id"],
                "lot_id": lot["id"],
                "sku_id": line["sku_id"],
                "qty": take,
                "picked_qty": 0,
                "status": "ASSIGNED",
            })
            store.pick_tasks[pt["id"]] = pt
            remaining -= take


def touch_bin_for_lot(lot):
    """Cascade: recompute owning bin occupied_cc (derived) and bump its version."""
    bin_rec = store.bins.get(lot["bin_id"])
    if bin_rec is not None:
        touch(bin_rec)


def pick_tasks_for_order(order_id):
    return [pt for pt in store.pick_tasks.values() if pt["order_id"] == order_id]


def cartons_for_order(order_id, statuses=None):
    items = [c for c in store.cartons.values() if c["order_id"] == order_id]
    if statuses is not None:
        items = [c for c in items if c["status"] in statuses]
    return items


def consume_reservations(order):
    """Ship-time: for each ASSIGNED/PICKED pick task lot, reserved -= qty AND
    on_hand -= qty, leaving available unchanged (PRD §3.8)."""
    for pt in pick_tasks_for_order(order["id"]):
        if pt["status"] == "PICKED":
            lot = store.inventory_lots.get(pt["lot_id"])
            if lot is None:
                continue
            qty = pt["qty"]
            lot["reserved_qty"] -= qty
            lot["on_hand_qty"] -= qty
            touch(lot)
            touch_bin_for_lot(lot)


def release_reservations_short(order):
    """Short-time (PRD §3.5): release the unconsumed reservation for EVERY line
    (shortfall = qty - picked_qty), then close every still-ASSIGNED pick task.

    The reservation release applies to all of the order's pick tasks regardless of
    their pick status; the SHORT_CLOSED transition applies only to still-ASSIGNED
    tasks. A SHORT order is terminal and never ships, so the reserved-but-unpicked
    units must be returned to availability here."""
    for pt in pick_tasks_for_order(order["id"]):
        lot = store.inventory_lots.get(pt["lot_id"])
        shortfall = pt["qty"] - pt["picked_qty"]
        if lot is not None and shortfall > 0:
            lot["reserved_qty"] -= shortfall
            touch(lot)
            touch_bin_for_lot(lot)
        if pt["status"] == "ASSIGNED":
            pt["status"] = "SHORT_CLOSED"
            touch(pt)


def release_reservations_cancel(order):
    """Cancel-from-RESERVED: release the full reservation per ASSIGNED pick task."""
    for pt in pick_tasks_for_order(order["id"]):
        if pt["status"] == "ASSIGNED":
            lot = store.inventory_lots.get(pt["lot_id"])
            if lot is not None:
                lot["reserved_qty"] -= pt["qty"]
                touch(lot)
                touch_bin_for_lot(lot)
            pt["status"] = "SHORT_CLOSED"
            touch(pt)


def maybe_complete_wave(wave_id):
    """Advance RELEASED wave to COMPLETED when every member order is terminal."""
    if not wave_id:
        return
    wave = store.waves.get(wave_id)
    if wave is None or wave["status"] != "RELEASED":
        return
    members = [o for o in store.orders.values() if o["wave_id"] == wave_id]
    if members and all(o["status"] in TERMINAL_ORDER_STATES for o in members):
        wave["status"] = "COMPLETED"
        touch(wave)
