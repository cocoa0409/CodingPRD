from flask import Blueprint

import calc
import clock
import db
import services
from auth import authenticate, ROLE_SANCTUARY_DIRECTOR, ROLE_BARN_MANAGER
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OVER_RECEIPT,
    ERR_DAY_ALREADY_CLOSED,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_enum,
    as_number,
    body,
    get_path_or_404,
    pagination_args,
    parse_dt,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("feed", __name__)

READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_BARN_MANAGER]
D = calc.D


# --------------------------------------------------------------------------
# Purchase orders
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/purchase-orders")
def create_purchase_order():
    authenticate([ROLE_BARN_MANAGER])
    data = body()
    feed_type = as_enum(require_present(data, "feed_type"), "feed_type", calc.FEED_TYPES)
    quantity = as_number(require_present(data, "quantity_lbs"), "quantity_lbs")
    if quantity <= 0:
        raise_err(ERR_INVALID_REQUEST, "quantity_lbs must be > 0")
    unit = as_number(require_present(data, "unit_cents_per_lb"), "unit_cents_per_lb")
    if unit <= 0:
        raise_err(ERR_INVALID_REQUEST, "unit_cents_per_lb must be > 0")
    qty_dec = calc.dec_num(quantity)
    unit_dec = calc.dec_num(unit)
    rec = services.new_entity(
        {
            "feed_type": feed_type,
            "quantity_lbs": qty_dec,
            "unit_cents_per_lb": unit_dec,
            "estimated_total_cents": calc.rhu_int(qty_dec * unit_dec),
            "actual_total_cents": 0,
            "delivery_surcharge_cents": None,
            "grand_total_cents": None,
            "received_lbs": D("0"),
            "status": "DRAFT",
        }
    )
    db.purchase_orders[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/purchase-orders")
def list_purchase_orders():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("feed_type", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.purchase_orders.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/purchase-orders/<po_id>")
def get_purchase_order(po_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.purchase_orders, po_id)))


@bp.post("/rescue-ops/purchase-orders/<po_id>/mark-ordered")
def mark_ordered(po_id):
    authenticate([ROLE_BARN_MANAGER])
    rec = get_path_or_404(db.purchase_orders, po_id)
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Purchase order is not DRAFT")
    rec["status"] = "ORDERED"
    services.touch(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/purchase-orders/<po_id>/receive")
def receive_order(po_id):
    authenticate([ROLE_BARN_MANAGER])
    rec = get_path_or_404(db.purchase_orders, po_id)
    data = body()
    qty_raw = as_number(require_present(data, "quantity_received_lbs"), "quantity_received_lbs")
    if qty_raw <= 0:
        raise_err(ERR_INVALID_REQUEST, "quantity_received_lbs must be > 0")
    expiry = parse_dt(require_present(data, "expiry_date"), "expiry_date")
    if rec["status"] not in ("ORDERED", "PARTIALLY_RECEIVED"):
        raise_err(ERR_INVALID_STATE, "Purchase order is not open for receipts")
    received_qty = calc.rhu(calc.dec_num(qty_raw), 2)
    if rec["received_lbs"] + received_qty > rec["quantity_lbs"]:
        raise_err(ERR_OVER_RECEIPT, "Receipt exceeds the ordered quantity")

    lot = services.new_entity(
        {
            "feed_type": rec["feed_type"],
            "purchase_order_id": rec["id"],
            "quantity_lbs": received_qty,
            "initial_lbs": received_qty,
            "unit_cents_per_lb": rec["unit_cents_per_lb"],
            "lot_cost_cents": calc.lot_cost(received_qty, rec["unit_cents_per_lb"]),
            "expiry_date": expiry,
            "received_at": clock.now(),
        }
    )
    db.feed_lots[lot["id"]] = lot
    rec["received_lbs"] += received_qty
    rec["actual_total_cents"] += lot["lot_cost_cents"]
    if rec["received_lbs"] == rec["quantity_lbs"]:
        rec["status"] = "RECEIVED"
        rec["delivery_surcharge_cents"] = calc.surcharge(rec["actual_total_cents"])
        rec["grand_total_cents"] = rec["actual_total_cents"] + rec["delivery_surcharge_cents"]
    else:
        rec["status"] = "PARTIALLY_RECEIVED"
    services.touch(rec)
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Feed lots
# --------------------------------------------------------------------------
@bp.get("/rescue-ops/feed-lots")
def list_feed_lots():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("feed_type", "purchase_order_id"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.feed_lots.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/feed-lots/<lot_id>")
def get_feed_lot(lot_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.feed_lots, lot_id)))


# --------------------------------------------------------------------------
# Supply summary (computed on read)
# --------------------------------------------------------------------------
@bp.get("/rescue-ops/feed-inventory/summary")
def feed_summary():
    authenticate(READ_ROLES)
    now = clock.now()
    demand = calc.daily_demand()
    mult = calc.seasonal_multiplier(now.month)
    summaries = []
    for ft in calc.FEED_TYPES:
        daily = demand[ft]
        usable = sum(
            (lot["quantity_lbs"] for lot in db.feed_lots.values()
             if lot["feed_type"] == ft and lot["expiry_date"] >= now),
            D("0"),
        )
        inbound = sum(
            (po["quantity_lbs"] - po["received_lbs"] for po in db.purchase_orders.values()
             if po["feed_type"] == ft and po["status"] in ("ORDERED", "PARTIALLY_RECEIVED")),
            D("0"),
        )
        if daily == 0:
            tight = None
            committed = None
            reorder = False
        else:
            scaled = daily * mult
            tight = calc.rhu(usable / scaled, 2)
            committed = calc.rhu((usable + inbound) / scaled, 2)
            reorder = tight < D("30")
        summaries.append(
            {
                "feed_type": ft,
                "daily_demand_lbs": float(calc.rhu(daily, 2)),
                "usable_lbs": float(calc.rhu(usable, 2)),
                "inbound_ordered_lbs": float(calc.rhu(inbound, 2)),
                "seasonal_multiplier": float(mult),
                "days_of_supply_tight": float(tight) if tight is not None else None,
                "days_of_supply_committed": float(committed) if committed is not None else None,
                "reorder_required": reorder,
            }
        )
    return ok_object({"summaries": summaries})


# --------------------------------------------------------------------------
# Day close (ops-run checkpoint)
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/feed-inventory/close-day")
def close_day():
    authenticate([ROLE_BARN_MANAGER])
    data = body()
    close_date = parse_dt(require_present(data, "close_date"), "close_date")
    day_key = close_date.date()
    if day_key in db.closed_dates:
        raise_err(ERR_DAY_ALREADY_CLOSED, "This calendar date has already been closed")

    demand = calc.daily_demand()
    mult = calc.seasonal_multiplier(close_date.month)
    consumed_out = {}
    wasted_out = {}
    for ft in calc.FEED_TYPES:
        # 1) Expiry waste first.
        wasted = D("0")
        for lot in db.feed_lots.values():
            if lot["feed_type"] != ft:
                continue
            if lot["expiry_date"] < close_date and lot["quantity_lbs"] > 0:
                wasted += lot["quantity_lbs"]
                lot["quantity_lbs"] = D("0")
                services.touch(lot)
        # 2) Demand, rounded to 2dp.
        rounded_demand = calc.rhu(demand[ft] * mult, 2)
        # 3) FEFO drawdown over usable lots (expiry ASC, tie created_at ASC).
        usable_lots = [
            lot
            for lot in db.feed_lots.values()
            if lot["feed_type"] == ft and lot["expiry_date"] >= close_date and lot["quantity_lbs"] > 0
        ]
        usable_lots.sort(key=lambda l: (l["expiry_date"], l["created_at"], l["_seq"]))
        total_usable = sum((l["quantity_lbs"] for l in usable_lots), D("0"))
        consumed = min(rounded_demand, total_usable)
        shortfall = rounded_demand - consumed
        remaining = consumed
        for lot in usable_lots:
            if remaining <= 0:
                break
            take = min(lot["quantity_lbs"], remaining)
            lot["quantity_lbs"] -= take
            remaining -= take
            services.touch(lot)
        rec = services.new_entity(
            {
                "close_date": close_date,
                "feed_type": ft,
                "consumed_lbs": calc.rhu(consumed, 2),
                "wasted_lbs": calc.rhu(wasted, 2),
                "shortfall_lbs": calc.rhu(shortfall, 2),
            },
            ledger=True,
        )
        db.day_closes[rec["id"]] = rec
        consumed_out[ft] = float(calc.rhu(consumed, 2))
        wasted_out[ft] = float(calc.rhu(wasted, 2))

    db.closed_dates.add(day_key)
    from util import iso_z

    return ok_object(
        {"closed_date": iso_z(close_date), "consumed_lbs": consumed_out, "wasted_lbs": wasted_out}
    )


@bp.get("/rescue-ops/feed-day-closes")
def list_day_closes():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    value = query_str("feed_type")
    if value is not None:
        filters.append(("feed_type", value))
    rows, total = sorted_page(db.day_closes.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)
