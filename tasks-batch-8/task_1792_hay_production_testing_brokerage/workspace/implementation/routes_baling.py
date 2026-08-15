"""Custom baling service orders: request -> schedule -> start -> complete ->
dispute/resolve -> invoice, plus cancel."""

from flask import Blueprint, request

from auth import authorize
from db import store, new_id, stamp_new, touch
from domain import baling_invoice_cents
from errors import (
    ApiError, ERR_GROWER_NOT_FOUND, ERR_CUTTING_NOT_FOUND, ERR_BSO_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP, ERR_GROWER_SUSPENDED, ERR_BSO_WRONG_STATE,
    ERR_EQUIPMENT_BUFFER_CONFLICT, ERR_MOISTURE_UNSAFE,
)
from response import success
from serializers import baling_service_order_out
from util import (
    D, req, as_str, as_int, as_number, as_date,
    get_body, paginate, sorted_by_created,
)

bp = Blueprint("baling", __name__)


# --- BalingServiceOrder ---------------------------------------------------------

@bp.post("/api/baling-service-orders")
def create_bso():
    uid, role = authorize(["Grower", "PlatformAdmin"])
    body = get_body()
    grower_id = as_str(req(body, "grower_id"), "grower_id")
    cutting_id = as_str(req(body, "cutting_id"), "cutting_id")
    # Priority 4: body FKs in declared field order.
    grower = store["growers"].get(grower_id)
    if grower is None:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "grower not found")
    cutting = store["cuttings"].get(cutting_id)
    if cutting is None:
        raise ApiError(ERR_CUTTING_NOT_FOUND, 404, "cutting not found")
    # Priority 5: ownership.
    if role == "Grower" and grower_id != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only request baling for themselves")
    # Priority 9: referenced grower must be ACTIVE.
    if grower["status"] != "ACTIVE":
        raise ApiError(ERR_GROWER_SUSPENDED, 422, "referenced grower is suspended")
    order = stamp_new({
        "id": new_id(),
        "grower_id": grower_id,
        "cutting_id": cutting_id,
        "scheduled_date": None,
        "equipment_unit": None,
        "actual_bale_count": None,
        "baled_moisture_pct": None,
        "invoice_cents": None,
        "status": "REQUESTED",
    })
    store["baling_service_orders"][order["id"]] = order
    return success(baling_service_order_out(order), "object", 201)


@bp.get("/api/baling-service-orders")
def list_bsos():
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    items = list(store["baling_service_orders"].values())
    grower_filter = request.args.get("grower_id")
    if role == "Grower":
        grower_filter = uid
    cutting_filter = request.args.get("cutting_id")
    status_filter = request.args.get("status")
    if grower_filter is not None:
        items = [o for o in items if o["grower_id"] == grower_filter]
    if cutting_filter is not None:
        items = [o for o in items if o["cutting_id"] == cutting_filter]
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([baling_service_order_out(o) for o in page], "array", 200, meta)


def _load_bso(order_id):
    order = store["baling_service_orders"].get(order_id)
    if order is None:
        raise ApiError(ERR_BSO_NOT_FOUND, 404, "baling service order not found")
    return order


def _check_bso_owner(order, uid, role):
    if role == "Grower" and order["grower_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only act on their own baling orders")


@bp.get("/api/baling-service-orders/<order_id>")
def get_bso(order_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    order = _load_bso(order_id)
    _check_bso_owner(order, uid, role)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/schedule")
def schedule_bso(order_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    scheduled_date = as_date(req(body, "scheduled_date"), "scheduled_date")
    equipment_unit = as_str(req(body, "equipment_unit"), "equipment_unit")
    order = _load_bso(order_id)
    if order["status"] != "REQUESTED":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a REQUESTED order can be scheduled")
    cutting = store["cuttings"].get(order["cutting_id"])
    if cutting is None or cutting["status"] not in ("WINDOW_OPEN", "CUT"):
        raise ApiError(ERR_BSO_WRONG_STATE, 409,
                       "the referenced cutting must be WINDOW_OPEN or CUT to schedule")
    # Equipment buffer: same-unit jobs in SCHEDULED/IN_PROGRESS must differ by
    # >= 2 days (one idle day); |diff| < 2 days conflicts.
    for other in store["baling_service_orders"].values():
        if other["id"] == order["id"]:
            continue
        if other["equipment_unit"] != equipment_unit:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if other["scheduled_date"] is None:
            continue
        if abs((scheduled_date - other["scheduled_date"]).days) < 2:
            raise ApiError(ERR_EQUIPMENT_BUFFER_CONFLICT, 409,
                           "the equipment unit has another job within less than two days")
    order["scheduled_date"] = scheduled_date
    order["equipment_unit"] = equipment_unit
    order["status"] = "SCHEDULED"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/start")
def start_bso(order_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    order = _load_bso(order_id)
    if order["status"] != "SCHEDULED":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a SCHEDULED order can be started")
    order["status"] = "IN_PROGRESS"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/complete")
def complete_bso(order_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    actual_bale_count = as_int(req(body, "actual_bale_count"), "actual_bale_count")
    if actual_bale_count < 0:
        from util import invalid
        invalid("actual_bale_count must be zero or greater")
    baled_moisture_pct = as_number(req(body, "baled_moisture_pct"), "baled_moisture_pct")
    order = _load_bso(order_id)
    if order["status"] != "IN_PROGRESS":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only an IN_PROGRESS order can be completed")
    # Moisture safety gate: > 20.0 is unsafe; exactly 20.0 completes normally.
    if D(baled_moisture_pct) > D("20.0"):
        raise ApiError(ERR_MOISTURE_UNSAFE, 422, "bale moisture above 20.0 is unsafe")
    order["actual_bale_count"] = actual_bale_count
    order["baled_moisture_pct"] = baled_moisture_pct
    order["status"] = "COMPLETED"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/dispute")
def dispute_bso(order_id):
    uid, role = authorize(["Grower", "PlatformAdmin"])
    order = _load_bso(order_id)
    _check_bso_owner(order, uid, role)
    if order["status"] != "COMPLETED":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a COMPLETED order can be disputed")
    order["status"] = "DISPUTED"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/resolve")
def resolve_bso(order_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    order = _load_bso(order_id)
    if order["status"] != "DISPUTED":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a DISPUTED order can be resolved")
    order["status"] = "COMPLETED"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/invoice")
def invoice_bso(order_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    order = _load_bso(order_id)
    if order["status"] != "COMPLETED":
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a COMPLETED order can be invoiced")
    invoice = baling_invoice_cents(order["actual_bale_count"], order["baled_moisture_pct"])
    order["invoice_cents"] = invoice
    order["status"] = "INVOICED"
    touch(order)
    grower = store["growers"].get(order["grower_id"])
    if grower is not None:
        grower["outstanding_balance_cents"] = grower["outstanding_balance_cents"] + invoice
        touch(grower)
    return success(baling_service_order_out(order), "object", 200)


@bp.post("/api/baling-service-orders/<order_id>/cancel")
def cancel_bso(order_id):
    uid, role = authorize(["Grower", "PlatformAdmin"])
    order = _load_bso(order_id)
    _check_bso_owner(order, uid, role)
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError(ERR_BSO_WRONG_STATE, 409, "only a REQUESTED or SCHEDULED order can be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    return success(baling_service_order_out(order), "object", 200)
