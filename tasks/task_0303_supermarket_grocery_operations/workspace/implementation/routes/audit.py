"""Cycle counts and end-of-day reconciliation."""
from datetime import datetime, timezone

from flask import Blueprint, request

from auth import require_role
from common import (
    stamp_new, touch, require_dict, get_int, get_dt, pagination_params, paginate,
)
from clock import clock
from db import db, now_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST,
    ERR_CYCLE_COUNT_NOT_DRAFT, ERR_CYCLE_COUNT_NOT_SUBMITTED, ERR_CYCLE_COUNT_NOT_CANCELLABLE,
    ERR_EOD_NOT_OPEN, ERR_EOD_OPEN_CYCLE_COUNTS,
)
from lookup import get_department, get_product, get_cycle_count, get_eod
from inventory import product_inventory_rollup, fefo_deplete, fefo_available
from response import success, list_response
from serializers import ser_cycle_count, ser_eod

bp = Blueprint("audit", __name__)


def _parse_iso(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dept_book_value(department_id):
    return sum(
        p["on_hand_value_cents"]
        for p in db.products.values()
        if p["department_id"] == department_id
    )


# ---------------- Cycle Counts ----------------

@bp.route("/cycle-counts", methods=["POST"])
def create_cycle_count():
    require_role("InventoryAuditor", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    department_id = body.get("department_id")
    if not isinstance(department_id, str) or not department_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "department_id is required")
    get_department(department_id)
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    get_product(product_id)

    rec = stamp_new({
        "department_id": department_id,
        "product_id": product_id,
        "counted_qty": 0,
        "book_qty_snapshot": None,
        "variance_qty": None,
        "shrink_value_cents": 0,
        "status": "DRAFT",
    })
    db.cycle_counts[rec["id"]] = rec
    return success(ser_cycle_count(rec), status=201)


@bp.route("/cycle-counts/<cid>", methods=["GET"])
def get_cycle_count_route(cid):
    require_role("InventoryAuditor", "StoreManager")
    cc = get_cycle_count(cid)
    return success(ser_cycle_count(cc))


@bp.route("/cycle-counts", methods=["GET"])
def list_cycle_counts():
    require_role("InventoryAuditor", "StoreManager")
    limit, offset = pagination_params(request.args)
    items = list(db.cycle_counts.values())
    department_id = request.args.get("department_id")
    if department_id is not None:
        items = [c for c in items if c["department_id"] == department_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [c for c in items if c["product_id"] == product_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_cycle_count(c) for c in page], limit, offset, total)


@bp.route("/cycle-counts/<cid>/submit", methods=["POST"])
def submit_cycle_count(cid):
    require_role("InventoryAuditor", "StoreManager")
    cc = get_cycle_count(cid)
    body = require_dict(request.get_json(silent=True))
    if cc["status"] != "DRAFT":
        raise ApiError(ERR_CYCLE_COUNT_NOT_DRAFT[0], ERR_CYCLE_COUNT_NOT_DRAFT[1], "cycle count not draft")
    counted = get_int(body, "counted_qty", min_value=0)
    product = db.products.get(cc["product_id"])
    book = product["on_hand_qty"] if product is not None else 0
    cc["counted_qty"] = counted
    cc["book_qty_snapshot"] = book
    cc["variance_qty"] = counted - book
    cc["status"] = "SUBMITTED"
    touch(cc)
    return success(ser_cycle_count(cc))


@bp.route("/cycle-counts/<cid>/reconcile", methods=["POST"])
def reconcile_cycle_count(cid):
    require_role("InventoryAuditor", "StoreManager")
    cc = get_cycle_count(cid)
    if cc["status"] != "SUBMITTED":
        raise ApiError(ERR_CYCLE_COUNT_NOT_SUBMITTED[0], ERR_CYCLE_COUNT_NOT_SUBMITTED[1], "cycle count not submitted")
    product = db.products.get(cc["product_id"])
    variance = cc["variance_qty"]
    shrink = 0
    if variance < 0 and product is not None:
        # short: deplete |variance| FEFO; shrink = book value depleted.
        shortfall = -variance
        avail = fefo_available(product["id"])
        take = min(shortfall, avail)
        shrink = fefo_deplete(product, take)
    elif variance > 0 and product is not None:
        # over: create one adjustment lot valued at most-recent ACTIVE lot cost,
        # else product.unit_price_cents.
        unit_cost = _adjustment_unit_cost(product)
        lot = stamp_new({
            "product_id": product["id"],
            "shipment_id": None,
            "received_qty": variance,
            "remaining_qty": variance,
            "unit_cost_cents": unit_cost,
            "expiration_date": None,
            "status": "ACTIVE",
            "_expiration_dt": None,
        })
        db.inventory_lots[lot["id"]] = lot
    cc["shrink_value_cents"] = shrink
    cc["status"] = "RECONCILED"
    cc["_reconciled_clock"] = clock.now()
    touch(cc)
    if product is not None:
        product_inventory_rollup(product)
        # rollup may bump nothing on version; product version not bumped here
    return success(ser_cycle_count(cc))


def _adjustment_unit_cost(product):
    """Most recent ACTIVE lot's unit_cost_cents, else product.unit_price_cents."""
    active_lots = [
        l for l in db.inventory_lots.values()
        if l["product_id"] == product["id"] and l["status"] == "ACTIVE"
    ]
    if active_lots:
        active_lots.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
        return active_lots[-1]["unit_cost_cents"]
    return product["unit_price_cents"]


@bp.route("/cycle-counts/<cid>/cancel", methods=["POST"])
def cancel_cycle_count(cid):
    require_role("InventoryAuditor", "StoreManager")
    cc = get_cycle_count(cid)
    if cc["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_CYCLE_COUNT_NOT_CANCELLABLE[0], ERR_CYCLE_COUNT_NOT_CANCELLABLE[1], "cycle count not cancellable")
    cc["status"] = "CANCELLED"
    touch(cc)
    return success(ser_cycle_count(cc))


# ---------------- End-of-Day Reconciliation ----------------

@bp.route("/eod-reconciliations", methods=["POST"])
def create_eod():
    require_role("InventoryAuditor", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    department_id = body.get("department_id")
    if not isinstance(department_id, str) or not department_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "department_id is required")
    dept = get_department(department_id)
    business_date = get_dt(body, "business_date")  # validate ISO

    rec = stamp_new({
        "department_id": department_id,
        "business_date": body["business_date"],
        "opening_value_cents": _dept_book_value(department_id),
        "cogs_total_cents": 0,
        "shrink_total_cents": 0,
        "sales_total_cents": 0,
        "closing_value_cents": 0,
        "shrink_bps": 0,
        "shrink_alert": False,
        "status": "OPEN",
        "_open_clock": clock.now(),
    })
    db.eod_reconciliations[rec["id"]] = rec
    return success(ser_eod(rec), status=201)


@bp.route("/eod-reconciliations/<eid>", methods=["GET"])
def get_eod_route(eid):
    require_role("InventoryAuditor", "StoreManager")
    e = get_eod(eid)
    return success(ser_eod(e))


@bp.route("/eod-reconciliations", methods=["GET"])
def list_eod():
    require_role("InventoryAuditor", "StoreManager")
    limit, offset = pagination_params(request.args)
    items = list(db.eod_reconciliations.values())
    department_id = request.args.get("department_id")
    if department_id is not None:
        items = [e for e in items if e["department_id"] == department_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_eod(e) for e in page], limit, offset, total)


@bp.route("/eod-reconciliations/<eid>/close", methods=["POST"])
def close_eod(eid):
    require_role("InventoryAuditor", "StoreManager")
    e = get_eod(eid)
    if e["status"] != "OPEN":
        raise ApiError(ERR_EOD_NOT_OPEN[0], ERR_EOD_NOT_OPEN[1], "reconciliation not open")
    # blocked while the department has a SUBMITTED cycle count
    for cc in db.cycle_counts.values():
        if cc["department_id"] == e["department_id"] and cc["status"] == "SUBMITTED":
            raise ApiError(ERR_EOD_OPEN_CYCLE_COUNTS[0], ERR_EOD_OPEN_CYCLE_COUNTS[1], "open cycle counts")

    department_id = e["department_id"]
    dept = db.departments.get(department_id)
    # The EOD rollup window is half-open [reconciliation.created_at, now). Window
    # membership is tested on each event's created_at/updated_at, which are
    # wall-clock stamps (the moment of the actual mutation, per §2.4 — distinct
    # from the logical pricing/expiry clock of §2.8). The window end must use the
    # same wall-clock basis as those stamps, so it is wall-clock "now", not the
    # logical clock; otherwise an empty/inverted window would drop every in-window
    # sale, reconcile, pull, and expire.
    window_start = _parse_iso(e["created_at"])
    window_end = _parse_iso(now_iso())

    dept_product_ids = {p["id"] for p in db.products.values() if p["department_id"] == department_id}

    def in_window(iso_str):
        t = _parse_iso(iso_str)
        return window_start <= t < window_end

    # sales/cogs over FINALIZED sales in window with >=1 line on a dept product
    sales_total = 0
    cogs_total = 0
    for s in db.sales.values():
        if s["fulfillment_status"] != "FINALIZED":
            continue
        if not in_window(s["created_at"]):
            continue
        has_dept_line = any(
            l["sale_id"] == s["id"] and l["product_id"] in dept_product_ids
            for l in db.sale_line_items.values()
        )
        if not has_dept_line:
            continue
        sales_total += s["total_cents"]
        cogs_total += s["cogs_cents"]

    # shrink: reconciled dept cycle counts in window + dept lots PULLED/EXPIRED in
    # window. Membership uses the event's wall-clock updated_at (the moment of the
    # reconcile/pull/expire mutation), matching the §3.10 half-open window basis.
    shrink_total = 0
    for cc in db.cycle_counts.values():
        if cc["department_id"] != department_id:
            continue
        if cc["status"] != "RECONCILED":
            continue
        if not in_window(cc["updated_at"]):
            continue
        shrink_total += cc["shrink_value_cents"]
    for l in db.inventory_lots.values():
        if l["product_id"] not in dept_product_ids:
            continue
        if l["status"] not in ("PULLED", "EXPIRED"):
            continue
        if not in_window(l["updated_at"]):
            continue
        shrink_total += l.get("_shrink_value_cents", 0)

    closing_value = _dept_book_value(department_id)

    opening = e["opening_value_cents"]
    if opening == 0:
        shrink_bps = 0
    else:
        shrink_bps = (shrink_total * 10000) // opening
    alert_threshold = dept["shrink_alert_bps"] if dept is not None else 0
    shrink_alert = shrink_bps >= alert_threshold

    e["sales_total_cents"] = sales_total
    e["cogs_total_cents"] = cogs_total
    e["shrink_total_cents"] = shrink_total
    e["closing_value_cents"] = closing_value
    e["shrink_bps"] = shrink_bps
    e["shrink_alert"] = shrink_alert
    e["status"] = "CLOSED"
    touch(e)
    return success(ser_eod(e))
