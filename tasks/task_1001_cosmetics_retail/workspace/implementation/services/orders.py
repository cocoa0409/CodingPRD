"""Order lifecycle: line creation, reservation (allocation + final pricing),
payment, fulfilment, accrual and the cancellation cascade."""
from db import base_record, db, find_lot, touch
from errors import ApiError
from services.loyalty import append_ledger, tier_evaluation_rolling
from services.pricing import (
    apply_pricing,
    compute,
    eligible_samples,
    order_lines,
    points_accrual,
    sale_lines,
)
from util import iso

DRAWING_LINE_TYPES = ("SALE", "GWP")


def make_line(order, variant, quantity, line_type="SALE", promotion_id=None):
    """unit_price_cents and hygiene_class are snapshotted here and never move again."""
    product = db.products[variant["product_id"]]
    unit_price = 0 if line_type in ("GWP", "SAMPLE") else variant["price_cents"]
    line = base_record()
    line.update({
        "order_id": order["id"],
        "variant_id": variant["id"],
        "promotion_id": promotion_id,
        "line_type": line_type,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_gross_cents": unit_price * quantity,
        "line_discount_cents": 0,
        "line_net_cents": unit_price * quantity,
        "hygiene_class": product["hygiene_class"],
        "returned_quantity": 0,
        "_lot_id": None,
        "_drawn": 0,
        "_from_launch": 0,
    })
    db.order_lines[line["id"]] = line
    return line


def slot_occupancy(store_id, pickup_slot_start, exclude_order_id=None):
    count = 0
    for other in db.orders.values():
        if other["id"] == exclude_order_id:
            continue
        if other["store_id"] != store_id:
            continue
        if other["pickup_slot_start"] != pickup_slot_start:
            continue
        if other["fulfillment_status"] in ("RESERVED", "READY_FOR_PICKUP"):
            count += 1
    return count


def held_units(customer_id, variant_id, exclude_order_id):
    """Units of a limited variant this customer holds across non-CANCELLED orders,
    excluding the order now being reserved."""
    total = 0
    for line in db.order_lines.values():
        if line["variant_id"] != variant_id:
            continue
        if line["order_id"] == exclude_order_id:
            continue
        order = db.orders.get(line["order_id"])
        if not order or order["customer_id"] != customer_id:
            continue
        if order["fulfillment_status"] == "CANCELLED":
            continue
        total += line["quantity"]
    return total


class _Pools(object):
    """Remaining drawable units per lot while a reservation is being planned."""

    def __init__(self):
        self.launch = {}
        self.general = {}

    def _init(self, lot):
        if lot["id"] not in self.launch:
            self.launch[lot["id"]] = lot["launch_reserved_units"]
            self.general[lot["id"]] = max(0, lot["on_hand_units"] - lot["launch_reserved_units"])

    def available(self, lot):
        if lot is None:
            return 0, 0
        self._init(lot)
        return self.launch[lot["id"]], self.general[lot["id"]]

    def take(self, lot, from_launch, from_general):
        self._init(lot)
        self.launch[lot["id"]] -= from_launch
        self.general[lot["id"]] -= from_general


def reserve(order):
    """DRAFT -> RESERVED.  Gates run in the order pinned by PRD 3.6."""
    store = db.stores[order["store_id"]]
    customer = db.customers[order["customer_id"]]
    lines = sale_lines(order["id"])

    # gate: the fulfilling store must be ACTIVE
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_NOT_ACTIVE", "store %s is not ACTIVE" % store["id"])

    # gate: every sale line's variant must be sellable
    for line in lines:
        if db.variants[line["variant_id"]]["status"] != "ACTIVE":
            raise ApiError("ERR_VARIANT_NOT_SELLABLE", "variant %s is DISCONTINUED" % line["variant_id"])

    # gate: BOPIS pickup-slot head-count (>= capacity means full)
    if order["channel"] == "BOPIS":
        occupied = slot_occupancy(store["id"], order["pickup_slot_start"], exclude_order_id=order["id"])
        if occupied >= store["bopis_slot_capacity"]:
            raise ApiError("ERR_PICKUP_SLOT_FULL", "the requested pickup slot is full")

    tier = customer["tier"]
    limited = [l for l in lines if db.variants[l["variant_id"]]["is_limited_launch"]]

    # limited-launch gate 1: the tier window
    for line in limited:
        variant = db.variants[line["variant_id"]]
        status = variant["launch_status"]
        if status in ("SCHEDULED", "CLOSED"):
            raise ApiError("ERR_LAUNCH_NOT_OPEN", "the launch for variant %s is not open" % variant["id"])
        if status == "TIER_ROUGE_ONLY" and tier != "ROUGE":
            raise ApiError("ERR_LAUNCH_TIER_LOCKED", "this launch is open to ROUGE customers only")
        if status == "TIER_VIB_PLUS" and tier not in ("VIB", "ROUGE"):
            raise ApiError("ERR_LAUNCH_TIER_LOCKED", "this launch is open to VIB and ROUGE customers only")

    # limited-launch gate 2: the per-customer cap (held + requested <= cap)
    for line in limited:
        variant = db.variants[line["variant_id"]]
        held = held_units(order["customer_id"], variant["id"], order["id"])
        if held + line["quantity"] > variant["per_customer_cap"]:
            raise ApiError("ERR_LAUNCH_CAP_EXCEEDED", "per-customer cap exceeded for variant %s" % variant["id"])

    # limited-launch gate 3 / ordinary stock: plan the waterfall draw
    pools = _Pools()
    plan = []
    for line in lines:
        variant = db.variants[line["variant_id"]]
        lot = find_lot(order["store_id"], line["variant_id"])
        launch_avail, general_avail = pools.available(lot)
        wanted = line["quantity"]

        if variant["is_limited_launch"]:
            from_launch = min(wanted, launch_avail)
            from_general = wanted - from_launch
            if from_general > general_avail:
                if not order["allow_partial"]:
                    raise ApiError("ERR_INSUFFICIENT_STOCK", "insufficient stock for variant %s" % variant["id"])
                from_general = general_avail
        else:
            from_launch = 0
            from_general = wanted
            if from_general > general_avail:
                if not order["allow_partial"]:
                    raise ApiError("ERR_INSUFFICIENT_STOCK", "insufficient stock for variant %s" % variant["id"])
                from_general = general_avail

        drawn = from_launch + from_general
        if lot is not None:
            pools.take(lot, from_launch, from_general)
        plan.append((line, lot, from_launch, from_general, drawn))

    quantities = dict((line["id"], drawn) for line, _lot, _fl, _fg, drawn in plan)

    # FINAL pricing over whatever quantities survived clipping
    result = compute(lines, lambda l: quantities[l["id"]], tier, order["points_redeemed"])

    # points gates
    if order["points_redeemed"] > customer["points_balance"]:
        raise ApiError("ERR_INSUFFICIENT_POINTS", "the customer does not hold that many points")
    if result["points_value_cents"] > result["discounted_subtotal_cents"]:
        raise ApiError("ERR_POINTS_EXCEED_SUBTOTAL", "points may not buy more than the basket is worth")

    # ---------------- commit ----------------
    order["tier_at_reserve"] = tier

    touched_lots = {}
    for line, lot, from_launch, from_general, drawn in plan:
        if lot is None:
            line["_lot_id"] = None
            line["_drawn"] = 0
            line["_from_launch"] = 0
            continue
        lot["launch_reserved_units"] -= from_launch
        lot["on_hand_units"] -= drawn
        lot["reserved_units"] += drawn
        line["_lot_id"] = lot["id"]
        line["_drawn"] = drawn
        line["_from_launch"] = from_launch
        touched_lots[lot["id"]] = lot

    apply_pricing(order, lines, result, "FINAL")

    # gift and sample lines are materialised only now
    discounted = order["discounted_subtotal_cents"]
    gwp = result["gwp"]
    if gwp and gwp.get("gift_variant_id"):
        gift_variant = db.variants.get(gwp["gift_variant_id"])
        if gift_variant is not None:
            gift_lot = find_lot(order["store_id"], gift_variant["id"])
            _launch_avail, general_avail = pools.available(gift_lot)
            if gift_lot is not None and general_avail >= gwp["gift_quantity"]:
                gift_line = make_line(order, gift_variant, gwp["gift_quantity"], "GWP", gwp["id"])
                gift_lot["on_hand_units"] -= gwp["gift_quantity"]
                gift_lot["reserved_units"] += gwp["gift_quantity"]
                pools.take(gift_lot, 0, gwp["gift_quantity"])
                gift_line["_lot_id"] = gift_lot["id"]
                gift_line["_drawn"] = gwp["gift_quantity"]
                gift_line["_from_launch"] = 0
                touched_lots[gift_lot["id"]] = gift_lot

    for sample in eligible_samples(discounted):
        if not sample.get("gift_variant_id"):
            continue
        sample_variant = db.variants.get(sample["gift_variant_id"])
        if sample_variant is None:
            continue
        # sample lines never touch an inventory lot
        make_line(order, sample_variant, sample["gift_quantity"], "SAMPLE", sample["id"])

    for lot in touched_lots.values():
        touch(lot)

    if order["points_redeemed"] > 0:
        append_ledger(customer, "REDEEM", -order["points_redeemed"], order["id"])
        touch(customer)

    order["fulfillment_status"] = "RESERVED"
    touch(order)
    return order


def fulfil(order):
    """HAND_OVER / SHIP: reserved units become sold, points accrue, spend grows,
    the tier is re-evaluated in ROLLING mode."""
    customer = db.customers[order["customer_id"]]

    moved = {}
    for line in order_lines(order["id"]):
        if line["line_type"] not in DRAWING_LINE_TYPES:
            continue
        if not line["_lot_id"] or line["_drawn"] <= 0:
            continue
        moved[line["_lot_id"]] = moved.get(line["_lot_id"], 0) + line["_drawn"]

    for lot_id, units in moved.items():
        lot = db.lots[lot_id]
        lot["reserved_units"] -= units
        lot["sold_units"] += units
        touch(lot)

    order["fulfilled_at"] = iso(db.clock)
    order["points_earned"] = points_accrual(order)

    append_ledger(customer, "EARN", order["points_earned"], order["id"])
    customer["qualifying_spend_cents"] += order["total_due_cents"]
    customer["lifetime_spend_cents"] += order["total_due_cents"]
    tier_evaluation_rolling(customer)
    touch(customer)

    touch(order)
    return order


def cancel(order):
    """Undo every effect the reservation caused, in a chain."""
    customer = db.customers[order["customer_id"]]
    previous_fulfillment = order["fulfillment_status"]

    if previous_fulfillment in ("RESERVED", "READY_FOR_PICKUP"):
        # hop 1: release inventory, restoring the launch earmark exactly
        released = {}
        for line in order_lines(order["id"]):
            if line["line_type"] not in DRAWING_LINE_TYPES:
                continue
            if not line["_lot_id"] or line["_drawn"] <= 0:
                continue
            entry = released.setdefault(line["_lot_id"], [0, 0])
            entry[0] += line["_drawn"]
            entry[1] += line["_from_launch"]
            line["_drawn"] = 0
            line["_from_launch"] = 0

        for lot_id, (drawn, from_launch) in released.items():
            lot = db.lots[lot_id]
            lot["reserved_units"] -= drawn
            lot["on_hand_units"] += drawn
            lot["launch_reserved_units"] += from_launch
            touch(lot)

        # hop 3/4: give the redeemed points back
        if order["points_redeemed"] > 0:
            append_ledger(customer, "REVERSAL", order["points_redeemed"], order["id"])
            touch(customer)

        # the payment dimension settles
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "VOIDED"
        elif order["payment_status"] == "CAPTURED":
            order["payment_status"] = "REFUNDED"
            order["refunded_cents"] = order["total_due_cents"]

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return order
