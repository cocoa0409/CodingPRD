"""Purchase order endpoints."""

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LTA_CEILING_EXCEEDED,
    ERR_LTA_NOT_ACTIVE,
    ERR_LTA_NOT_FOUND,
    ERR_PO_HAS_ACTIVE_WORK,
    ERR_PO_NOT_ACCEPTED,
    ERR_PO_NOT_CANCELLABLE,
    ERR_PO_NOT_FOUND,
    ERR_PO_NUMBER_EXISTS,
    ERR_STALE_LTA_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import compute_po_pricing
from validate import (
    json_body,
    no_unknown,
    opt_bool,
    paginate,
    req_enum_list,
    req_int,
    req_str,
)

bp = Blueprint("purchase_orders", __name__)

CM = "ContractsManager"

FLOWDOWN_CLAUSES = {
    "AS9102_FAI",
    "AS9100D_QMS",
    "DFARS_COUNTERFEIT_PREVENTION",
    "CUSTOMER_SOURCE_INSPECTION",
    "DELEGATED_INSPECTION_PERMITTED",
}


def get_po(po_id):
    po = db.purchase_orders.get(po_id)
    if po is None:
        raise ApiError(ERR_PO_NOT_FOUND, 404, "Purchase order %s not found" % po_id)
    return po


@bp.route("/api/purchase-orders", methods=["POST"])
def create_po():
    require_roles(CM)
    data = json_body()
    no_unknown(
        data,
        {
            "lta_id",
            "po_number",
            "part_number",
            "part_revision",
            "quantity",
            "flowdown_clauses",
            "requires_special_process",
            "delivery_year",
            "expected_lta_version",
        },
    )
    lta_id = req_str(data, "lta_id")
    po_number = req_str(data, "po_number")
    part_number = req_str(data, "part_number")
    part_revision = req_str(data, "part_revision")
    quantity = req_int(data, "quantity", min_val=1)
    flowdown = req_enum_list(data, "flowdown_clauses", FLOWDOWN_CLAUSES)
    rsp = opt_bool(data, "requires_special_process", False)
    delivery_year = req_int(data, "delivery_year")
    if "expected_lta_version" not in data or data["expected_lta_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: expected_lta_version")
    expected = data["expected_lta_version"]

    lta = db.ltas.get(lta_id)
    if lta is None:
        raise ApiError(ERR_LTA_NOT_FOUND, 404, "LTA %s not found" % lta_id)
    # OCC (priority 4) precedes the LTA-active state check (priority 5)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != lta["version"]:
        raise ApiError(ERR_STALE_LTA_VERSION, 412, "expected_lta_version is stale")
    if lta["status"] != "ACTIVE":
        raise ApiError(ERR_LTA_NOT_ACTIVE, 409, "LTA is not ACTIVE")
    if any(
        po["lta_id"] == lta["id"] and po["po_number"] == po_number
        for po in db.purchase_orders.values()
    ):
        raise ApiError(ERR_PO_NUMBER_EXISTS, 409, "po_number already exists under this LTA")

    pinned_version = lta["version"]
    unit_price, total = compute_po_pricing(lta, quantity, rsp, delivery_year)
    if total > lta["remaining_ceiling_cents"]:
        raise ApiError(ERR_LTA_CEILING_EXCEEDED, 402, "PO total exceeds LTA remaining ceiling")

    rec = base_record(db.new_id())
    rec.update(
        {
            "lta_id": lta["id"],
            "po_number": po_number,
            "part_number": part_number,
            "part_revision": part_revision,
            "quantity": quantity,
            "flowdown_clauses": flowdown,
            "requires_special_process": rsp,
            "delivery_year": delivery_year,
            "unit_price_cents": unit_price,
            "total_cents": total,
            "lta_version_pinned": pinned_version,
            "unreleased_quantity": quantity,
            "delivered_quantity": 0,
            "status": "RECEIVED",
            "_closed_dt": None,
        }
    )
    db.purchase_orders[rec["id"]] = rec
    lta["remaining_ceiling_cents"] -= total
    touch(lta)  # agreement version advances on PO creation
    return success_object(public(rec), 201)


@bp.route("/api/purchase-orders", methods=["GET"])
def list_pos():
    require_roles(*ALL_ROLES)
    items = list(db.purchase_orders.values())
    lta_id = request.args.get("lta_id")
    part_number = request.args.get("part_number")
    status = request.args.get("status")
    if lta_id is not None:
        items = [p for p in items if p["lta_id"] == lta_id]
    if part_number is not None:
        items = [p for p in items if p["part_number"] == part_number]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/purchase-orders/<poId>", methods=["GET"])
def get_one_po(poId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_po(poId)))


@bp.route("/api/purchase-orders/<poId>/accept", methods=["POST"])
def accept_po(poId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    po = get_po(poId)
    if po["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "PO accept requires RECEIVED")
    if not po["flowdown_clauses"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "flowdown_clauses must be non-empty to accept")
    po["status"] = "ACCEPTED"
    touch(po)
    return success_object(public(po))


@bp.route("/api/purchase-orders/<poId>/release", methods=["POST"])
def release_po(poId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    po = get_po(poId)
    if po["status"] != "ACCEPTED":
        raise ApiError(ERR_PO_NOT_ACCEPTED, 409, "PO release requires ACCEPTED")
    lta = db.ltas.get(po["lta_id"])
    if lta is None or lta["status"] != "ACTIVE":
        raise ApiError(ERR_LTA_NOT_ACTIVE, 409, "LTA is not ACTIVE")
    po["status"] = "RELEASED"
    touch(po)
    return success_object(public(po))


@bp.route("/api/purchase-orders/<poId>/cancel", methods=["POST"])
def cancel_po(poId):
    require_roles(CM)
    data = json_body()
    no_unknown(data, set())
    po = get_po(poId)
    if po["status"] not in ("RECEIVED", "ACCEPTED", "RELEASED"):
        raise ApiError(ERR_PO_NOT_CANCELLABLE, 409, "PO is not cancellable")
    active_wos = [
        w
        for w in db.work_orders.values()
        if w["po_id"] == po["id"]
        and w["status"] in ("IN_PRODUCTION", "QUALITY_HOLD", "FINAL_INSPECTION")
    ]
    if active_wos:
        raise ApiError(ERR_PO_HAS_ACTIVE_WORK, 409, "PO has active work orders")

    # Cascade: cancel unstarted work orders, restoring unreleased quantity
    for wo in db.work_orders.values():
        if wo["po_id"] == po["id"] and wo["status"] in ("PLANNED", "RELEASED"):
            wo["status"] = "CANCELLED"
            po["unreleased_quantity"] += wo["quantity"]
            touch(wo)
    po["status"] = "CANCELLED"
    touch(po)

    lta = db.ltas.get(po["lta_id"])
    if lta is not None:
        lta["remaining_ceiling_cents"] += po["total_cents"]
        touch(lta)  # agreement version advances on PO cancel
    return success_object(public(po))
