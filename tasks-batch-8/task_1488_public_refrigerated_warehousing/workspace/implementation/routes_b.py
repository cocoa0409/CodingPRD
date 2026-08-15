"""Routes: inventory lots, pallets, outbound orders, allocations."""

from flask import Blueprint, request

from core import (
    ALL_ROLES, ApiError, DB, as_int, as_str, authenticate, authorize,
    check_ownership, clock_now, get_body, get_or_404, list_response,
    new_record, ok_object, req_present, touch,
)
from views import (
    PRESENT_STATUSES, active_allocations, active_rate_card, allocation_view,
    find_lot, handling_out_fee, lot_metrics, lot_view, open_invoice, order_view,
    outstanding_balance, pallet_view,
)

bp = Blueprint("routes_b", __name__)


# ----------------------------------------------------------------------------
# Inventory lots
# ----------------------------------------------------------------------------

@bp.route("/api/lots/<lid>", methods=["GET"])
def get_lot(lid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    lot = get_or_404("lots", lid, "lot")
    check_ownership(role, uid, lot["customer_id"])
    return ok_object(lot_view(lot))


@bp.route("/api/lots", methods=["GET"])
def list_lots():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_status = request.args.get("status")
    records = list(DB["lots"].values())
    if role == "CustomerAdmin":
        records = [l for l in records if l["customer_id"] == uid]
    if f_customer is not None:
        records = [l for l in records if l["customer_id"] == f_customer]
    if f_status is not None:
        records = [l for l in records if lot_metrics(l)[1] == f_status]
    return list_response(records, lot_view)


# ----------------------------------------------------------------------------
# Pallets
# ----------------------------------------------------------------------------

@bp.route("/api/pallets/<pid>", methods=["GET"])
def get_pallet(pid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    pallet = get_or_404("pallets", pid, "pallet")
    check_ownership(role, uid, pallet["customer_id"])
    return ok_object(pallet_view(pallet))


@bp.route("/api/pallets", methods=["GET"])
def list_pallets():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_lot = request.args.get("lot_id")
    f_zone = request.args.get("zone_id")
    f_receipt = request.args.get("receipt_id")
    f_status = request.args.get("status")
    f_quality = request.args.get("quality")
    records = list(DB["pallets"].values())
    if role == "CustomerAdmin":
        records = [p for p in records if p["customer_id"] == uid]
    if f_customer is not None:
        records = [p for p in records if p["customer_id"] == f_customer]
    if f_lot is not None:
        records = [p for p in records if p["lot_id"] == f_lot]
    if f_zone is not None:
        records = [p for p in records if p["zone_id"] == f_zone]
    if f_receipt is not None:
        records = [p for p in records if p["receipt_id"] == f_receipt]
    if f_status is not None:
        records = [p for p in records if p["status"] == f_status]
    if f_quality is not None:
        records = [p for p in records if p["quality"] == f_quality]
    return list_response(records, pallet_view)


@bp.route("/api/pallets/<pid>/release-quarantine", methods=["POST"])
def release_quarantine(pid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    pallet = get_or_404("pallets", pid, "pallet")
    if pallet["quality"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409, "pallet is not QUARANTINED")
    pallet["quality"] = "OK"
    touch(pallet)
    return ok_object(pallet_view(pallet))


@bp.route("/api/pallets/<pid>/dispose", methods=["POST"])
def dispose_pallet(pid):
    uid, role = authenticate()
    authorize(role, {"QualityManager"})
    pallet = get_or_404("pallets", pid, "pallet")
    if pallet["status"] != "STORED" or pallet["quality"] != "RECALLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a STORED pallet with quality RECALLED may be disposed")
    pallet["status"] = "DISPOSITIONED"
    pallet["out_at"] = clock_now()
    pallet["out_reason"] = "DISPOSED"
    touch(pallet)
    return ok_object(pallet_view(pallet))


# ----------------------------------------------------------------------------
# Outbound orders
# ----------------------------------------------------------------------------

def _release_order_allocations(order, demote=True):
    """Release every ACTIVE allocation on the order; pallets return to STORED.
    When demote is True an ALLOCATED order falls back to SUBMITTED."""
    for alloc in active_allocations(order["id"]):
        alloc["status"] = "RELEASED"
        touch(alloc)
        pallet = DB["pallets"][alloc["pallet_id"]]
        if pallet["status"] == "ALLOCATED":
            pallet["status"] = "STORED"
            touch(pallet)
    if demote and order["status"] == "ALLOCATED":
        order["status"] = "SUBMITTED"


def _fifo_candidates(order):
    """STORED + OK pallets of the customer's lots of this product (restricted to
    the lot override when present), ordered production_date, received_at,
    created_at — never by pallet id."""
    keyed = []
    for p in DB["pallets"].values():
        if p["customer_id"] != order["customer_id"]:
            continue
        if p["status"] != "STORED" or p["quality"] != "OK":
            continue
        lot = DB["lots"][p["lot_id"]]
        if lot["product_code"] != order["product_code"]:
            continue
        if order["lot_code"] is not None and lot["lot_code"] != order["lot_code"]:
            continue
        keyed.append((lot["production_date"], p["received_at"], p["created_at"], p["_seq"], p))
    keyed.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return [t[4] for t in keyed]


def _credit_check(customer, fee):
    if outstanding_balance(customer["id"]) + fee > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 409,
                       "outstanding balance plus the estimated fee exceeds the credit limit")


@bp.route("/api/outbound-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    data = get_body()
    customer_id = as_str(req_present(data, "customer_id"), "customer_id")
    product_code = as_str(req_present(data, "product_code"), "product_code")
    requested = as_int(req_present(data, "requested_pallets"), "requested_pallets", minimum=1)
    lot_code = None
    if "lot_code" in data and data["lot_code"] is not None:
        lot_code = as_str(data["lot_code"], "lot_code")
    authorize(role, {"CustomerAdmin"})
    check_ownership(role, uid, customer_id)
    cust = get_or_404("customers", customer_id, "customer")
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "customer is SUSPENDED")
    order = new_record({
        "customer_id": customer_id,
        "product_code": product_code,
        "lot_code": lot_code,
        "requested_pallets": requested,
        "estimated_handling_out_cents": None,
        "final_handling_out_cents": None,
        "status": "DRAFT",
    })
    DB["orders"][order["id"]] = order
    return ok_object(order_view(order), 201)


@bp.route("/api/outbound-orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    order = get_or_404("orders", oid, "order")
    check_ownership(role, uid, order["customer_id"])
    return ok_object(order_view(order))


@bp.route("/api/outbound-orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_status = request.args.get("status")
    records = list(DB["orders"].values())
    if role == "CustomerAdmin":
        records = [o for o in records if o["customer_id"] == uid]
    if f_customer is not None:
        records = [o for o in records if o["customer_id"] == f_customer]
    if f_status is not None:
        records = [o for o in records if o["status"] == f_status]
    return list_response(records, order_view)


@bp.route("/api/outbound-orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin"})
    order = get_or_404("orders", oid, "order")
    check_ownership(role, uid, order["customer_id"])
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "order is not DRAFT")
    cust = DB["customers"][order["customer_id"]]
    # Pinned gate order (PRD §3.5): standing -> rate card -> lot exists ->
    # lot not recalled -> estimate -> credit check.
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "customer is SUSPENDED")
    card = active_rate_card(order["customer_id"])
    if card is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_CARD", 409, "customer has no ACTIVE rate card")
    if order["lot_code"] is not None:
        lot = find_lot(order["customer_id"], order["product_code"], order["lot_code"])
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", 404, "no lot matches the order's lot_code")
        if lot_metrics(lot)[1] == "RECALLED":
            raise ApiError("ERR_LOT_RECALLED", 409, "the named lot stands at RECALLED")
    estimate = handling_out_fee(order["customer_id"], order["requested_pallets"], card)
    _credit_check(cust, estimate)
    order["estimated_handling_out_cents"] = estimate
    order["status"] = "SUBMITTED"
    touch(order)
    return ok_object(order_view(order))


@bp.route("/api/outbound-orders/<oid>/allocate", methods=["POST"])
def allocate_order(oid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    order = get_or_404("orders", oid, "order")
    if order["status"] not in ("SUBMITTED", "SHORTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "order is not SUBMITTED or SHORTED")
    needed = order["requested_pallets"] - len(active_allocations(order["id"]))
    if needed > 0:
        for pallet in _fifo_candidates(order)[:needed]:
            alloc = new_record({
                "order_id": order["id"],
                "pallet_id": pallet["id"],
                "lot_id": pallet["lot_id"],
                "status": "ACTIVE",
            })
            DB["allocations"][alloc["id"]] = alloc
            pallet["status"] = "ALLOCATED"
            touch(pallet)
    allocated = len(active_allocations(order["id"]))
    order["status"] = "ALLOCATED" if allocated == order["requested_pallets"] else "SHORTED"
    touch(order)
    return ok_object(order_view(order))


@bp.route("/api/outbound-orders/<oid>/amend", methods=["POST"])
def amend_order(oid):
    uid, role = authenticate()
    data = get_body()
    requested = as_int(req_present(data, "requested_pallets"), "requested_pallets", minimum=1)
    expected = as_int(req_present(data, "expected_order_version"), "expected_order_version")
    authorize(role, {"CustomerAdmin"})
    order = get_or_404("orders", oid, "order")
    check_ownership(role, uid, order["customer_id"])
    if order["status"] not in ("DRAFT", "SHORTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "only a DRAFT or SHORTED order can be amended")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_order_version does not match the order's current version")
    # Re-price the estimate and re-run the credit check before committing.
    card = active_rate_card(order["customer_id"])
    if card is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_CARD", 409, "customer has no ACTIVE rate card")
    estimate = handling_out_fee(order["customer_id"], requested, card)
    cust = DB["customers"][order["customer_id"]]
    _credit_check(cust, estimate)
    # Commit: release allocations, replace quantity, DRAFT, bump version.
    _release_order_allocations(order, demote=False)
    order["requested_pallets"] = requested
    order["estimated_handling_out_cents"] = estimate
    order["status"] = "DRAFT"
    touch(order)
    return ok_object(order_view(order))


@bp.route("/api/outbound-orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    order = get_or_404("orders", oid, "order")
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", 409, "order is not ALLOCATED")
    allocs = active_allocations(order["id"])
    card = active_rate_card(order["customer_id"])
    fee = handling_out_fee(order["customer_id"], len(allocs), card) if card else 0
    now = clock_now()
    for alloc in allocs:
        alloc["status"] = "FULFILLED"
        touch(alloc)
        pallet = DB["pallets"][alloc["pallet_id"]]
        pallet["status"] = "SHIPPED"
        pallet["out_at"] = now
        pallet["out_reason"] = "SHIPPED"
        touch(pallet)
    order["final_handling_out_cents"] = fee
    order["status"] = "SHIPPED"
    touch(order)
    inv = open_invoice(order["customer_id"])
    inv["handling_out_cents"] += fee
    touch(inv)
    return ok_object(order_view(order))


@bp.route("/api/outbound-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin"})
    order = get_or_404("orders", oid, "order")
    check_ownership(role, uid, order["customer_id"])
    if order["status"] not in ("DRAFT", "SUBMITTED", "SHORTED", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "order can no longer be cancelled")
    _release_order_allocations(order, demote=False)
    order["status"] = "CANCELLED"
    touch(order)
    return ok_object(order_view(order))


# ----------------------------------------------------------------------------
# Allocations
# ----------------------------------------------------------------------------

@bp.route("/api/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    alloc = get_or_404("allocations", aid, "allocation")
    order = DB["orders"][alloc["order_id"]]
    check_ownership(role, uid, order["customer_id"])
    return ok_object(allocation_view(alloc))


@bp.route("/api/allocations", methods=["GET"])
def list_allocations():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_order = request.args.get("order_id")
    f_pallet = request.args.get("pallet_id")
    f_lot = request.args.get("lot_id")
    f_status = request.args.get("status")
    records = list(DB["allocations"].values())
    if role == "CustomerAdmin":
        records = [a for a in records
                   if DB["orders"][a["order_id"]]["customer_id"] == uid]
    if f_order is not None:
        records = [a for a in records if a["order_id"] == f_order]
    if f_pallet is not None:
        records = [a for a in records if a["pallet_id"] == f_pallet]
    if f_lot is not None:
        records = [a for a in records if a["lot_id"] == f_lot]
    if f_status is not None:
        records = [a for a in records if a["status"] == f_status]
    return list_response(records, allocation_view)


@bp.route("/api/allocations/<aid>/release", methods=["POST"])
def release_allocation(aid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    alloc = get_or_404("allocations", aid, "allocation")
    if alloc["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "allocation is not ACTIVE")
    alloc["status"] = "RELEASED"
    touch(alloc)
    pallet = DB["pallets"][alloc["pallet_id"]]
    if pallet["status"] == "ALLOCATED":
        pallet["status"] = "STORED"
        touch(pallet)
    order = DB["orders"][alloc["order_id"]]
    if order["status"] == "ALLOCATED":
        order["status"] = "SUBMITTED"
        touch(order)
    return ok_object(allocation_view(alloc))
