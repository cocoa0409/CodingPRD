"""PartUsage endpoints: consume van stock on a call, return full lines."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_forbidden_ownership, err_validation)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import append_event, reorder_trigger, wall_now
from routes.service_calls import (get_call_or_404, ensure_not_cancelled,
                                  onsite_dispatch_for)
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("part_usages", __name__)

READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "BillingClerk"]
CHARGE_TYPES = {"CUSTOMER_PAY", "SHOP_GUARANTEE"}


def _get_usage(usage_id):
    u = store.part_usages.get(usage_id)
    if u is None:
        raise err_not_found("PartUsage not found")
    return u


@bp.route("/roadside/service-calls/<serviceCallId>/part-usages",
          methods=["POST"])
def create_usage(serviceCallId):
    uid, role = auth(["Technician"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("van_stock_item_id", "string", required=True),
        Field("qty", "int", required=True, min_val=1),
        Field("charge_type", "enum", enum=CHARGE_TYPES),
    ])
    item = store.van_stock.get(vals["van_stock_item_id"])
    if item is None:
        raise err_not_found("VanStockItem not found")
    ensure_not_cancelled(call)
    if call["status"] != "REPAIR_IN_PROGRESS":
        raise err_invalid_state("Part usage requires REPAIR_IN_PROGRESS")
    disp = onsite_dispatch_for(call)
    if disp is None or disp["technician_id"] != uid:
        raise err_forbidden_ownership(
            "Actor is not the call's ON_SITE dispatch technician")
    charge_type = vals.get("charge_type", "CUSTOMER_PAY")
    if charge_type == "SHOP_GUARANTEE" and not call.get("is_comeback"):
        raise err_validation(
            "SHOP_GUARANTEE is valid only on comeback calls")
    if item["technician_id"] != disp["technician_id"]:
        raise ApiError("ERR_PART_NOT_ON_VAN",
                       "Stock item belongs to a different technician's van",
                       409)
    if vals["qty"] > item["qty_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_VAN_STOCK",
                       "Usage qty exceeds van qty_on_hand", 409)
    item["qty_on_hand"] -= vals["qty"]
    touch(item, wall_now())
    unit_price = item["unit_retail_cents"]
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "van_stock_item_id": item["id"],
        "part_number": item["part_number"],
        "qty": vals["qty"],
        "charge_type": charge_type,
        "unit_price_cents": unit_price,
        "line_total_cents": vals["qty"] * unit_price,
        "status": "POSTED",
        "posted_at": store.clock,
    })
    store.part_usages[rec["id"]] = rec
    append_event(call["id"], "PART_POSTED", role, uid)
    reorder_trigger(item)
    return success(serialize("part_usage", rec), status=201)


@bp.route("/roadside/part-usages/<partUsageId>", methods=["GET"])
def get_usage(partUsageId):
    auth(READ_ROLES)
    return success(serialize("part_usage", _get_usage(partUsageId)))


@bp.route("/roadside/part-usages", methods=["GET"])
def list_usages():
    auth(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    item_f = request.args.get("van_stock_item_id")
    status_f = request.args.get("status")
    items = sorted(store.part_usages.values(), key=lambda r: r["_seq"])
    if call_f is not None:
        items = [u for u in items if u["service_call_id"] == call_f]
    if item_f is not None:
        items = [u for u in items if u["van_stock_item_id"] == item_f]
    if status_f is not None:
        items = [u for u in items if u["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("part_usage", u) for u in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/part-usages/<partUsageId>/return", methods=["POST"])
def return_usage(partUsageId):
    uid, role = auth(["Technician"])
    usage = _get_usage(partUsageId)
    validate_body(request.get_json(silent=True), [])
    if usage["status"] != "POSTED":
        raise err_invalid_state("Only a POSTED usage can be returned")
    call = store.service_calls.get(usage["service_call_id"])
    if call is None:
        raise err_not_found("ServiceCall not found")
    if call["status"] != "REPAIR_IN_PROGRESS":
        raise err_invalid_state(
            "Returns are allowed only while the repair is in progress")
    disp = onsite_dispatch_for(call)
    if disp is None or disp["technician_id"] != uid:
        raise err_forbidden_ownership(
            "Actor is not the call's ON_SITE dispatch technician")
    item = store.van_stock.get(usage["van_stock_item_id"])
    if item is not None:
        item["qty_on_hand"] += usage["qty"]
        touch(item, wall_now())
    usage["status"] = "RETURNED"
    touch(usage, wall_now())
    append_event(call["id"], "PART_RETURNED", role, uid)
    return success(serialize("part_usage", usage))
