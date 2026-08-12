"""Sales order endpoints: capture/pricing, rush review, schedule, cancel."""
from flask import Blueprint, request

from .domain import (
    CUSTOM_MIN_GALLONS,
    CUSTOM_MIN_GALLONS_RUSH,
    CUSTOM_SETUP_FEE_CENTS,
    RUSH_DAILY_LIMIT,
    RUSH_FLAT_CENTS,
    RUSH_PCT,
    RUSH_PCT_THRESHOLD_CENTS,
    SIZE_CODES,
    ser_order,
)
from .errors import ApiError, bad_request, invalid_state, not_found, unprocessable
from .store import now, store
from .util import (
    D,
    auth,
    body,
    list_response,
    new_record,
    round0,
    success,
    touch,
    v_arr,
    v_bool,
    v_num,
    v_state_code,
    v_str,
)

bp = Blueprint("orders", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


def _dealer_owns(order, user_id, role):
    if role == "Dealer" and order["customer_id"] != user_id:
        raise ApiError(403, "ERR_FORBIDDEN", "Dealer may only act on its own orders")


@bp.post("/coatings/orders")
def create_order():
    user_id, _role = auth(("Dealer",))
    b = body()
    # gate 2: entity-backed ownership (before remaining schema checks)
    if "customer_id" in b and b["customer_id"] is not None and b["customer_id"] != user_id:
        raise ApiError(403, "ERR_FORBIDDEN", "Dealer may only place orders for its own customer record")
    customer_id = v_str(b, "customer_id")
    destination = v_state_code(b, "destination_state_code")
    rush_flag = v_bool(b, "rush_flag")
    raw_lines = v_arr(b, "lines")
    if len(raw_lines) == 0:
        raise bad_request("lines must be non-empty")
    parsed = []
    for i, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            raise bad_request("lines[%d] must be an object" % i)
        fid = v_str(entry, "formula_id")
        gallons = v_num(entry, "gallons", gt=0)
        size_code = None
        if "size_code" in entry and entry["size_code"] is not None:
            size_code = entry["size_code"]
            if size_code not in SIZE_CODES:
                raise bad_request("size_code must be one of %s" % ", ".join(SIZE_CODES))
        parsed.append((fid, gallons, size_code))
    # gate 4: existence
    if customer_id not in store.customers:
        raise not_found()
    formulas = []
    for fid, _g, _s in parsed:
        f = store.formulas.get(fid)
        if f is None:
            raise not_found()
        formulas.append(f)
    # gate 8: every line's formula must be ACTIVE
    for f in formulas:
        if f["status"] != "ACTIVE":
            raise unprocessable("ERR_FORMULA_NOT_ACTIVE", "Every order line formula must be ACTIVE")
    # gate 11: custom minimums (raised when rushed)
    min_gal = CUSTOM_MIN_GALLONS_RUSH if rush_flag else CUSTOM_MIN_GALLONS
    for (fid, gallons, _s), f in zip(parsed, formulas):
        if f["is_custom"] and gallons < min_gal:
            raise unprocessable("ERR_CUSTOM_MINIMUM_NOT_MET", "Custom-formula line below the minimum gallons")
    # pinned pricing order: line amounts -> subtotal -> setup -> rush fee (0 here) -> total
    subtotal = 0
    custom_lines = 0
    norm_lines = []
    for (fid, gallons, size_code), f in zip(parsed, formulas):
        base = store.tint_bases[f["tint_base_id"]]
        subtotal += round0(D(gallons) * D(base["unit_price_per_gal_cents"]))
        if f["is_custom"]:
            custom_lines += 1
        norm_lines.append({"formula_id": fid, "gallons": gallons, "size_code": size_code})
    setup_fee = CUSTOM_SETUP_FEE_CENTS * custom_lines
    rec = new_record()
    rec.update({
        "customer_id": customer_id,
        "destination_state_code": destination,
        "rush_flag": rush_flag,
        "lines": norm_lines,
        "is_custom_order": custom_lines > 0,
        "subtotal_cents": subtotal,
        "setup_fee_cents": setup_fee,
        "rush_fee_cents": 0,
        "total_cents": subtotal + setup_fee,
        "status": "RUSH_REVIEW" if rush_flag else "PLACED",
        "rush_approved_date": None,
    })
    store.orders[rec["id"]] = rec
    return success(ser_order(rec), 201)


@bp.get("/coatings/orders/<oid>")
def get_order(oid):
    user_id, role = auth(ALL)
    rec = store.orders.get(oid)
    if rec is None:
        raise not_found()
    _dealer_owns(rec, user_id, role)
    return success(ser_order(rec), 200)


@bp.get("/coatings/orders")
def list_orders():
    user_id, role = auth(ALL)
    recs = list(store.orders.values())
    if role == "Dealer":
        recs = [o for o in recs if o["customer_id"] == user_id]
    cust = request.args.get("customer_id")
    if cust is not None:
        recs = [o for o in recs if o["customer_id"] == cust]
    st = request.args.get("status")
    if st is not None:
        recs = [o for o in recs if o["status"] == st]
    return list_response(recs, ser_order)


@bp.post("/coatings/orders/<oid>/rush-approve")
def rush_approve(oid):
    auth(("PlantManager",))
    rec = store.orders.get(oid)
    if rec is None:
        raise not_found()
    if rec["status"] != "RUSH_REVIEW":
        raise invalid_state("Order is not in RUSH_REVIEW")
    today = now().date().isoformat()
    approvals_today = sum(1 for o in store.orders.values() if o.get("rush_approved_date") == today)
    if approvals_today >= RUSH_DAILY_LIMIT:
        raise unprocessable("ERR_RUSH_CAPACITY_EXCEEDED", "Daily rush approval capacity reached")
    subtotal = rec["subtotal_cents"]
    if subtotal >= RUSH_PCT_THRESHOLD_CENTS:
        rush_fee = round0(RUSH_PCT * D(subtotal))
    else:
        rush_fee = RUSH_FLAT_CENTS
    rec["rush_fee_cents"] = rush_fee
    rec["total_cents"] = rec["subtotal_cents"] + rec["setup_fee_cents"] + rush_fee
    rec["rush_approved_date"] = today
    rec["status"] = "PLACED"
    touch(rec)
    return success(ser_order(rec), 200)


@bp.post("/coatings/orders/<oid>/rush-reject")
def rush_reject(oid):
    auth(("PlantManager",))
    rec = store.orders.get(oid)
    if rec is None:
        raise not_found()
    if rec["status"] != "RUSH_REVIEW":
        raise invalid_state("Order is not in RUSH_REVIEW")
    rec["rush_flag"] = False
    rec["status"] = "PLACED"
    touch(rec)
    return success(ser_order(rec), 200)


@bp.post("/coatings/orders/<oid>/schedule")
def schedule_order(oid):
    auth(("ProductionOperator",))
    b = body()
    batch_id = v_str(b, "batch_id")
    rec = store.orders.get(oid)
    if rec is None:
        raise not_found()
    batch = store.batches.get(batch_id)
    if batch is None:
        raise not_found()
    if rec["status"] != "PLACED":
        raise invalid_state("Order is not PLACED")
    if batch.get("order_id") != oid:
        raise unprocessable("ERR_ORDER_BATCH_MISMATCH", "Batch does not belong to this order")
    if batch["status"] != "PLANNED":
        raise invalid_state("Batch is not PLANNED")
    rec["status"] = "SCHEDULED"
    touch(rec)
    return success(ser_order(rec), 200)


@bp.post("/coatings/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = auth(("Dealer", "PlantManager"))
    rec = store.orders.get(oid)
    if rec is None:
        raise not_found()
    _dealer_owns(rec, user_id, role)
    if rec["status"] not in ("PLACED", "RUSH_REVIEW", "SCHEDULED", "BLOCKED"):
        raise invalid_state("Order cannot be cancelled from %s" % rec["status"])
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(ser_order(rec), 200)
