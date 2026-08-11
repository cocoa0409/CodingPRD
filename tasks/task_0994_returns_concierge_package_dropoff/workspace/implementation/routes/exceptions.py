"""ExceptionCase endpoints: open, investigate loop, resolve (OCC + SoD),
appeal, close — with the per-kind cascades from the ExceptionCase machine."""

from flask import Blueprint, request

import db
from db import store, stamp, touch
from errors import (
    ApiError, bad_request, invalid_state, already_terminal, not_found,
)
from services import (
    EXCEPTION_KINDS, RESOLUTIONS, ORDER_TERMINAL, EXCEPTION_OPEN_STATUSES,
    FRAUD_STRIKE_LIMIT, APPEAL_LIMIT,
    ser_exception, get_or_404, order_items, open_exception, reevaluate_order,
    active_label, held_reservation, release_reservation, void_label,
    merchant_plan, line_deduction_cents,
)
from util import (
    require_roles, respond, body, req_str, req_enum, req_field,
    opt_bool, paginate, is_int,
)

bp = Blueprint("exceptions", __name__)


def _case_order(case):
    return store["orders"][case["return_order_id"]]


def _check_case_access(uid, role, case):
    order = _case_order(case)
    if role == "Shopper" and order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own cases")
    if role == "MerchantAdmin" and order["merchant_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "MerchantAdmin may act only on its own merchant's cases")
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")


@bp.post("/exception-cases")
def create_exception():
    uid, role = require_roles("SupportAgent", "LocationOperator")
    b = body(required=True)
    order_id = req_str(b, "return_order_id")
    kind = req_enum(b, "kind", EXCEPTION_KINDS)
    note = req_field(b, "note")
    if not isinstance(note, str):
        bad_request("note must be a string")
    item_id = b.get("return_item_id")
    if kind == "DAMAGED_ITEM" and not item_id:
        bad_request("return_item_id is required for kind DAMAGED_ITEM")
    order = get_or_404("orders", order_id)
    if item_id is not None:
        item = get_or_404("items", item_id)
        if item["return_order_id"] != order_id:
            # PRD §2.8 P7: references never cross merchant boundaries.
            owning = store["orders"].get(item["return_order_id"])
            if owning is not None and owning.get("merchant_id") != order.get(
                    "merchant_id"):
                raise ApiError("ERR_CROSS_MERCHANT_REFERENCE", 422,
                               "return_item_id belongs to another merchant")
            bad_request("return_item_id does not belong to return_order_id")
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")
    if order["status"] in ORDER_TERMINAL:
        already_terminal("Order is in a terminal state")
    if open_exception(order_id) is not None:
        raise ApiError("ERR_EXCEPTION_OPEN_EXISTS", 409,
                       "Another non-terminal exception already exists on this order")
    case = {
        "return_order_id": order_id,
        "return_item_id": item_id,
        "kind": kind,
        "note": note,
        "status": "OPEN",
        "resolution": None,
        "opened_by_user_id": uid,
        "resolved_by_user_id": None,
        "appeal_count": 0,
    }
    stamp(case)
    store["exceptions"][case["id"]] = case
    if order["status"] in ("DROPPED_OFF", "IN_TRANSIT", "INSPECTING"):
        order["status"] = "EXCEPTION_PENDING"
        touch(order)
    return respond(ser_exception(case), 201)


@bp.get("/exception-cases/<cid>")
def get_exception(cid):
    uid, role = require_roles("SupportAgent", "PlatformAdmin", "LocationOperator",
                              "Shopper", "MerchantAdmin")
    case = get_or_404("exceptions", cid)
    _check_case_access(uid, role, case)
    return respond(ser_exception(case))


@bp.get("/exception-cases")
def list_exceptions():
    require_roles("SupportAgent", "PlatformAdmin")
    items = list(store["exceptions"].values())
    order_id = request.args.get("return_order_id")
    item_id = request.args.get("return_item_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if order_id is not None:
        items = [c for c in items if c["return_order_id"] == order_id]
    if item_id is not None:
        items = [c for c in items if c.get("return_item_id") == item_id]
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return respond([ser_exception(c) for c in page], page=meta)


@bp.get("/return-orders/<oid>/exception-cases")
def list_order_exceptions(oid):
    uid, role = require_roles("Shopper", "MerchantAdmin", "SupportAgent",
                              "PlatformAdmin", "LocationOperator")
    order = get_or_404("orders", oid)
    if role == "Shopper" and order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own orders")
    if role == "MerchantAdmin" and order["merchant_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "MerchantAdmin may act only on its own merchant's orders")
    if role == "LocationOperator" and order.get("dropoff_location_id") != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")
    items = [c for c in store["exceptions"].values() if c["return_order_id"] == oid]
    page, meta = paginate(items)
    return respond([ser_exception(c) for c in page], page=meta)


def _case_state(case, allowed, action):
    if case["status"] == "CLOSED":
        already_terminal("Exception case is CLOSED")
    if case["status"] not in allowed:
        invalid_state("Case cannot be %sed from %s" % (action, case["status"]))


@bp.post("/exception-cases/<cid>/start-investigation")
def start_investigation(cid):
    require_roles("SupportAgent")
    case = get_or_404("exceptions", cid)
    _case_state(case, ("OPEN", "REOPENED"), "start-investigation")
    case["status"] = "INVESTIGATING"
    touch(case)
    return respond(ser_exception(case))


@bp.post("/exception-cases/<cid>/request-shopper-info")
def request_shopper_info(cid):
    require_roles("SupportAgent")
    case = get_or_404("exceptions", cid)
    _case_state(case, ("INVESTIGATING",), "request-shopper-info")
    case["status"] = "AWAITING_SHOPPER"
    touch(case)
    return respond(ser_exception(case))


@bp.post("/exception-cases/<cid>/provide-shopper-info")
def provide_shopper_info(cid):
    uid, role = require_roles("Shopper")
    case = get_or_404("exceptions", cid)
    order = _case_order(case)
    if order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may respond only on its own cases")
    b = body(required=True)
    req_field(b, "response_note")
    _case_state(case, ("AWAITING_SHOPPER",), "provide-shopper-info")
    case["status"] = "INVESTIGATING"
    touch(case)
    return respond(ser_exception(case))


def _remark_item_defective(item):
    plan = merchant_plan(store["merchants"][
        store["orders"][item["return_order_id"]]["merchant_id"]])
    item["condition"] = "DEFECTIVE"
    if item["status"] == "PENDING":
        item["status"] = "INSPECTED"
        item["inspected_at"] = db.now()
    item["deduction_cents"] = line_deduction_cents(
        item["unit_price_cents"], item["quantity"], "DEFECTIVE", plan,
        apply_waiver=True)
    touch(item)


def _resolve_cascade(case, resolution):
    order = _case_order(case)
    kind = case["kind"]
    order_terminal = order["status"] in ORDER_TERMINAL
    if resolution == "APPROVED":
        if kind == "DAMAGED_ITEM":
            item = store["items"].get(case.get("return_item_id"))
            if item is not None and item["condition"] == "DAMAGED":
                _remark_item_defective(item)
            if not order_terminal:
                reevaluate_order(order)
        elif kind == "LABEL_FRAUD":
            shopper = store["shoppers"][order["shopper_id"]]
            shopper["fraud_strikes"] += 1
            if shopper["fraud_strikes"] >= FRAUD_STRIKE_LIMIT:
                shopper["status"] = "RESTRICTED"
            touch(shopper)
            if not order_terminal:
                order["status"] = "REJECTED_CLOSED"
                order["resolved_at"] = db.now()
                touch(order)
        elif kind == "LOST_PARCEL":
            for item in order_items(order["id"]):
                _remark_item_defective(item)
            if not order_terminal:
                reevaluate_order(order)
        elif kind == "OVERSIZE_REJECT":
            if order["status"] == "EXCEPTION_PENDING":
                label = active_label(order)
                if label is not None:
                    void_label(label)
                res = held_reservation(order["id"])
                if res is not None:
                    release_reservation(res)
                order["method"] = "HOME_PICKUP"
                order["status"] = "INITIATED"
                touch(order)
        else:  # WRONG_ITEM
            if not order_terminal:
                reevaluate_order(order)
    else:  # REJECTED
        if kind == "LOST_PARCEL":
            if not order_terminal:
                order["status"] = "REJECTED_CLOSED"
                order["resolved_at"] = db.now()
                touch(order)
        else:
            if not order_terminal:
                reevaluate_order(order)


@bp.post("/exception-cases/<cid>/resolve")
def resolve_exception(cid):
    uid, role = require_roles("SupportAgent")
    case = get_or_404("exceptions", cid)
    b = body(required=True)
    resolution = req_enum(b, "resolution", RESOLUTIONS)
    expected = req_field(b, "expected_exception_case_version")
    if not is_int(expected):
        bad_request("expected_exception_case_version must be an integer")
    # Priority 5: OCC before state and SoD.
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_exception_case_version does not match current version")
    _case_state(case, ("INVESTIGATING",), "resolve")
    # Priority 9: segregation of duties — resolver differs from opener.
    if uid == case["opened_by_user_id"]:
        raise ApiError("ERR_SOD_RESOLVER_EQUALS_OPENER", 403,
                       "Exception resolver must differ from opener")
    case["resolution"] = resolution
    case["resolved_by_user_id"] = uid
    case["status"] = "RESOLVED_APPROVED" if resolution == "APPROVED" \
        else "RESOLVED_REJECTED"
    touch(case)
    _resolve_cascade(case, resolution)
    return respond(ser_exception(case))


@bp.post("/exception-cases/<cid>/appeal")
def appeal_exception(cid):
    uid, role = require_roles("Shopper")
    case = get_or_404("exceptions", cid)
    order = _case_order(case)
    if order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may appeal only its own cases")
    b = body(required=True)
    req_field(b, "appeal_note")
    _case_state(case, ("RESOLVED_APPROVED", "RESOLVED_REJECTED"), "appeal")
    if case["appeal_count"] >= APPEAL_LIMIT:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED", 409,
                       "appeal_count already at 2")
    case["appeal_count"] += 1
    case["status"] = "REOPENED"
    touch(case)
    return respond(ser_exception(case))


@bp.post("/exception-cases/<cid>/close")
def close_exception(cid):
    require_roles("SupportAgent")
    case = get_or_404("exceptions", cid)
    _case_state(case, ("RESOLVED_APPROVED", "RESOLVED_REJECTED"), "close")
    case["status"] = "CLOSED"
    touch(case)
    return respond(ser_exception(case))
