from flask import Blueprint, request

import store
import response
import serialize
import calc
import services
from errors import ApiError
from helpers import (endpoint, get_body, field, lookup, require_fk, stamp_new,
                     touch, paginate, owner_check)

bp = Blueprint("orders", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end): conflict iff a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


def _new_order_record(member_id, station_id, channel, start, end):
    rec = {
        "member_id": member_id,
        "station_id": station_id,
        "fulfillment_channel": channel,
        "fill_window_start_at": start,
        "fill_window_end_at": end,
        "fulfillment_status": "CART",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "deposit_total_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "loyalty_points_earned": 0,
    }
    stamp_new(rec)
    store.DB["orders"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Order CRUD
# ---------------------------------------------------------------------------
@bp.post("/v1/orders")
@endpoint(["Member", "StoreClerk"])
def create_order():
    body = get_body()
    member_id = field(body, "member_id", required=True, kind="str")
    station_id = field(body, "station_id", required=True, kind="str")
    start = field(body, "fill_window_start_at", required=True, kind="datetime")
    end = field(body, "fill_window_end_at", required=True, kind="datetime")
    channel = field(body, "fulfillment_channel", kind="str",
                    enum={"IN_STORE", "DELIVERY"}, default="IN_STORE")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "fill_window_end_at must be after fill_window_start_at")
    owner_check(member_id)
    require_fk("members", member_id)
    require_fk("stations", station_id)
    # Temporal (priority 7): station fill-window overlap
    for o in store.DB["orders"].values():
        if o["station_id"] == station_id and o["fulfillment_status"] != "CANCELLED":
            if _windows_overlap(start, end, o["fill_window_start_at"], o["fill_window_end_at"]):
                raise ApiError("ERR_STATION_SESSION_OVERLAP",
                               "fill-window overlaps another order on this station")
    rec = _new_order_record(member_id, station_id, channel, start, end)
    return response.created(serialize.order_out(rec))


@bp.get("/v1/orders/<order_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_order(order_id):
    return response.ok(serialize.order_out(lookup("orders", order_id)))


@bp.get("/v1/orders")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_orders():
    member_id = request.args.get("member_id")
    station_id = request.args.get("station_id")
    fulfillment_status = request.args.get("fulfillment_status")
    recs = list(store.DB["orders"].values())
    if member_id is not None:
        recs = [o for o in recs if o["member_id"] == member_id]
    if station_id is not None:
        recs = [o for o in recs if o["station_id"] == station_id]
    if fulfillment_status is not None:
        recs = [o for o in recs if o["fulfillment_status"] == fulfillment_status]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.order_out(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Add provisional line
# ---------------------------------------------------------------------------
@bp.post("/v1/orders/<order_id>/lines")
@endpoint(["Member", "StoreClerk"])
def add_line(order_id):
    order = lookup("orders", order_id)
    owner_check(order["member_id"])
    body = get_body()
    product_id = field(body, "product_id", required=True, kind="str")
    container_id = field(body, "container_id", required=True, kind="str")
    estimated_gross_g = field(body, "estimated_gross_g", required=True, kind="int")
    product = require_fk("products", product_id)
    container = require_fk("containers", container_id)
    if order["fulfillment_status"] != "CART":
        raise ApiError("ERR_INVALID_ORDER_STATE", "lines may be added only to a CART order")
    member = store.DB["members"][order["member_id"]]
    declared_tare_g = container["declared_tare_g"]
    net = estimated_gross_g - declared_tare_g
    price = calc.refill_line_price(net, product, member["membership_tier"])
    rec = {
        "order_id": order_id,
        "product_id": product_id,
        "container_id": container_id,
        "bin_id": None,
        "declared_tare_g": declared_tare_g,
        "estimated_gross_g": estimated_gross_g,
        "gross_weight_g": None,
        "net_weight_g": net,
        "line_price_cents": price,
        "pricing_stage": "PROVISIONAL",
    }
    stamp_new(rec)
    store.DB["lines"][rec["id"]] = rec
    return response.created(serialize.line_out(rec))


# ---------------------------------------------------------------------------
# start-fill / checkout / cancel
# ---------------------------------------------------------------------------
@bp.post("/v1/orders/<order_id>/start-fill")
@endpoint(["StoreClerk"])
def start_fill(order_id):
    order = lookup("orders", order_id)
    if order["fulfillment_status"] != "CART":
        raise ApiError("ERR_INVALID_ORDER_STATE", "order must be CART to start filling")
    if len(services.nonvoided_lines(order_id)) == 0:
        raise ApiError("ERR_EMPTY_ORDER", "order has no non-voided lines")
    station = store.DB["stations"][order["station_id"]]
    if station["station_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "station is not OPEN")
    order["fulfillment_status"] = "FILLING"
    touch(order)
    return response.ok(serialize.order_out(order))


@bp.post("/v1/orders/<order_id>/checkout")
@endpoint(["Member", "StoreClerk"])
def checkout(order_id):
    order = lookup("orders", order_id)
    owner_check(order["member_id"])
    body = get_body()
    redeem_points = field(body, "redeem_points", kind="int", default=0)
    if order["fulfillment_status"] != "FILLING":
        raise ApiError("ERR_INVALID_ORDER_STATE", "order must be FILLING to checkout")
    nonvoided = services.nonvoided_lines(order_id)
    if any(l["pricing_stage"] != "FINAL" for l in nonvoided):
        raise ApiError("ERR_INVALID_ORDER_STATE", "every non-voided line must be FINAL")
    finals = [l for l in nonvoided if l["pricing_stage"] == "FINAL"]
    if len(finals) == 0:
        raise ApiError("ERR_EMPTY_ORDER", "order has no FINAL non-voided lines")

    # Deposit commitment: each ISSUED container on a FINAL line -> IN_USE + DEPOSIT_COMMIT
    committed_deposit = 0
    seen = set()
    for l in finals:
        cid = l["container_id"]
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        c = store.DB["containers"].get(cid)
        if c is not None and c["status"] == "ISSUED":
            c["status"] = "IN_USE"
            touch(c)
            committed_deposit += c["deposit_cents"]
            services.append_ledger(
                c["member_id"], "DEPOSIT_COMMIT",
                liability_delta=c["deposit_cents"],
                source_kind="CONTAINER", source_id=c["id"], memo="deposit commit at checkout",
            )

    subtotal, discount, deposit_total, tax, total = calc.order_totals(
        finals, store.DB["products"], committed_deposit, redeem_points
    )

    # Loyalty redemption ledger (points spent capped at member balance)
    if redeem_points and redeem_points > 0:
        balance = _loyalty_balance(order["member_id"])
        spent = min(redeem_points, balance)
        if spent > 0:
            services.append_ledger(
                order["member_id"], "LOYALTY_REDEEM", points_delta=-spent,
                source_kind="ORDER", source_id=order["id"], memo="loyalty redemption",
            )

    # Loyalty accrual on the settled subtotal (subtotal - discount)
    member = store.DB["members"][order["member_id"]]
    earned = calc.loyalty_points(subtotal - discount, member["membership_tier"])
    services.append_ledger(
        order["member_id"], "LOYALTY_ACCRUAL", points_delta=earned,
        source_kind="ORDER", source_id=order["id"], memo="loyalty accrual",
    )

    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["deposit_total_cents"] = deposit_total
    order["tax_cents"] = tax
    order["total_cents"] = total
    order["loyalty_points_earned"] = earned
    order["fulfillment_status"] = "FILLED"
    order["payment_status"] = "CAPTURED"
    if order["fulfillment_channel"] == "IN_STORE":
        order["fulfillment_status"] = "COMPLETED"
    touch(order)
    return response.ok(serialize.order_out(order))


@bp.post("/v1/orders/<order_id>/cancel")
@endpoint(["Member", "StoreClerk"])
def cancel_order(order_id):
    order = lookup("orders", order_id)
    owner_check(order["member_id"])
    if order["fulfillment_status"] not in ("CART", "FILLING"):
        raise ApiError("ERR_INVALID_ORDER_STATE", "only CART or FILLING orders may be cancelled")
    for l in services.nonvoided_lines(order_id):
        if l["pricing_stage"] == "FINAL" and l["bin_id"] is not None:
            b = store.DB["bins"].get(l["bin_id"])
            if b is not None:
                services.return_grams(b, l["net_weight_g"])
        l["pricing_stage"] = "VOIDED"
        touch(l)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return response.ok(serialize.order_out(order))


def _loyalty_balance(member_id):
    return sum(e["points_delta"] for e in store.DB["wallet_ledger"].values()
               if e["member_id"] == member_id)


# ---------------------------------------------------------------------------
# RefillLine reads + fill + void
# ---------------------------------------------------------------------------
@bp.get("/v1/refill-lines/<line_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_line(line_id):
    return response.ok(serialize.line_out(lookup("lines", line_id)))


@bp.get("/v1/refill-lines")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_lines():
    filters = {
        "order_id": request.args.get("order_id"),
        "product_id": request.args.get("product_id"),
        "container_id": request.args.get("container_id"),
        "bin_id": request.args.get("bin_id"),
        "pricing_stage": request.args.get("pricing_stage"),
    }
    recs = list(store.DB["lines"].values())
    for key, val in filters.items():
        if val is not None:
            recs = [l for l in recs if l[key] == val]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.line_out(l) for l in page], limit, offset, total)


@bp.post("/v1/refill-lines/<line_id>/fill")
@endpoint(["StoreClerk"])
def fill_line(line_id):
    line = lookup("lines", line_id)
    body = get_body()
    gross_weight_g = field(body, "gross_weight_g", required=True, kind="int")
    measured_tare_g = field(body, "measured_tare_g", required=True, kind="int")

    order = store.DB["orders"][line["order_id"]]
    # State (priority 4)
    if order["fulfillment_status"] != "FILLING":
        raise ApiError("ERR_INVALID_ORDER_STATE", "parent order must be FILLING to fill a line")
    if line["pricing_stage"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_ORDER_STATE", "line must be PROVISIONAL to fill")

    product = store.DB["products"][line["product_id"]]
    container = store.DB["containers"][line["container_id"]]

    # Business safety (priority 5): allergen, then bin resolution/quarantine
    hold = container["allergen_hold"]
    if hold != "NONE" and hold not in product["allergen_tags"]:
        raise ApiError("ERR_ALLERGEN_CONFLICT", "container allergen residue incompatible with product")
    bin_rec = services.resolve_bin(product["id"], order["station_id"])
    if bin_rec is None:
        raise ApiError("ERR_BIN_NOT_FOUND", "no bin for product at the order's station")
    if bin_rec["status"] == "QUARANTINED":
        raise ApiError("ERR_BIN_QUARANTINED", "resolved bin is quarantined")

    # Business referential (priority 6): container ownership
    if container["member_id"] != order["member_id"]:
        raise ApiError("ERR_CONTAINER_NOT_OWNED", "container is not owned by the order's member")

    # Structural constraint (priority 8): positive net
    net = gross_weight_g - measured_tare_g
    if net <= 0:
        raise ApiError("ERR_TARE_EXCEEDS_GROSS", "net weight must be positive")

    # Inventory/capacity (priority 9): sufficient stock
    if net > bin_rec["on_hand_g"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "insufficient bin stock")

    # ---- side effects ----
    member = store.DB["members"][order["member_id"]]
    container["measured_tare_g"] = measured_tare_g
    if product["allergen_tags"]:
        container["allergen_hold"] = product["allergen_tags"][0]
    touch(container)

    line["gross_weight_g"] = gross_weight_g
    line["net_weight_g"] = net
    line["bin_id"] = bin_rec["id"]
    line["line_price_cents"] = calc.refill_line_price(net, product, member["membership_tier"])
    line["pricing_stage"] = "FINAL"
    touch(line)

    services.deplete_bin(bin_rec, net)
    return response.ok(serialize.line_out(line))


@bp.post("/v1/refill-lines/<line_id>/void")
@endpoint(["StoreClerk"])
def void_line(line_id):
    line = lookup("lines", line_id)
    stage = line["pricing_stage"]
    if stage == "PROVISIONAL":
        line["pricing_stage"] = "VOIDED"
        touch(line)
    elif stage == "FINAL":
        order = store.DB["orders"][line["order_id"]]
        if order["payment_status"] != "UNPAID":
            raise ApiError("ERR_INVALID_ORDER_STATE", "cannot void a captured line")
        line["pricing_stage"] = "VOIDED"
        touch(line)
        if line["bin_id"] is not None:
            b = store.DB["bins"].get(line["bin_id"])
            if b is not None:
                services.return_grams(b, line["net_weight_g"])
    else:  # VOIDED
        raise ApiError("ERR_INVALID_ORDER_STATE", "line is already voided")
    return response.ok(serialize.line_out(line))
