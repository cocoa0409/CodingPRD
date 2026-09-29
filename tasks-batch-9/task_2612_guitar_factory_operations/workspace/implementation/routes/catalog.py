"""The option catalog and option selections (PRD 3.6)."""

from flask import Blueprint

import auth
import calc
import validate as v
from constants import (COMPLEXITY_CLASSES, OPTION_GROUPS,
                       REQUIRES_FINISH_SYSTEM, SELECTION_STATUSES)
from envelope import object_response, paginate
from errors import ApiError
from serialize import option_view, selection_view
from store import CATALOG, ORDERS, SELECTIONS, new_record, touch

bp = Blueprint("catalog", __name__)

OPEN_SELECTION_STATUSES = ("PENDING_APPROVAL", "SELECTED", "LOCKED")


@bp.post("/option-catalog")
def create_option():
    auth.require(auth.PLANT_ADMIN, auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    option_code = v.get_str(body, "option_code", min_len=1, max_len=64)
    option_group = v.get_enum(body, "option_group", OPTION_GROUPS)
    upcharge = v.get_int(body, "upcharge_cents", minimum=0)
    complexity = v.get_enum(body, "complexity_class", COMPLEXITY_CLASSES)
    lead_time = v.get_int(body, "lead_time_days", minimum=0)
    incompatible = v.get_code_list(body, "incompatible_option_codes",
                                   required=False, non_empty=False, default=[])
    requires_finish = v.get_enum(body, "requires_finish_system",
                                 REQUIRES_FINISH_SYSTEM, required=False,
                                 default="ANY")
    v.unique_code(CATALOG, "option_code", option_code)
    rec = new_record(CATALOG, {
        "option_code": option_code,
        "option_group": option_group,
        "upcharge_cents": upcharge,
        "complexity_class": complexity,
        "lead_time_days": lead_time,
        "incompatible_option_codes": incompatible,
        "requires_finish_system": requires_finish,
    }, versioned=False)
    return object_response(option_view(rec), 201)


@bp.get("/option-catalog/<option_id>")
def read_option(option_id):
    auth.require_staff()
    return object_response(option_view(
        v.fetch(CATALOG, option_id, "ERR_OPTION_CATALOG_NOT_FOUND")))


@bp.get("/option-catalog")
def list_options():
    auth.require_staff()
    rows = v.apply_filters(list(CATALOG.values()), [
        ("option_group", v.filter_enum("option_group", OPTION_GROUPS)),
        ("complexity_class", v.filter_enum("complexity_class",
                                           COMPLEXITY_CLASSES)),
    ])
    rows.sort(key=lambda r: r["option_code"])
    return paginate(rows, option_view)


@bp.post("/build-orders/<build_order_id>/option-selections")
def create_selection(build_order_id):
    user_id, _ = auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    option_id = v.get_id(body, "option_id")
    expected = v.get_int(body, "expected_build_order_version")
    quantity = v.get_int(body, "quantity", required=False, minimum=1,
                         maximum=4, default=1)
    v.get_id(body, "build_order_id", required=False)
    order = v.fetch(ORDERS, build_order_id, "ERR_BUILD_ORDER_NOT_FOUND")
    option = v.fetch(CATALOG, option_id, "ERR_OPTION_CATALOG_NOT_FOUND")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "the build order has moved on since it was read")
    requires = option["requires_finish_system"]
    if requires != "ANY" and requires != order["finish_system"]:
        raise ApiError("ERR_OPTION_FINISH_MISMATCH",
                       "the option demands a different finish system")
    for sel in SELECTIONS.values():
        if sel["build_order_id"] != order["id"]:
            continue
        if sel["status"] not in OPEN_SELECTION_STATUSES:
            continue
        other = CATALOG.get(sel["option_id"])
        if other is None:
            continue
        if option["option_code"] in other["incompatible_option_codes"] \
                or other["option_code"] in option["incompatible_option_codes"]:
            raise ApiError("ERR_OPTION_INCOMPATIBLE",
                           "the option conflicts with one already configured")

    rec = new_record(SELECTIONS, {
        "build_order_id": order["id"],
        "option_id": option_id,
        "quantity": quantity,
        "created_by_user_id": user_id,
        "locked_upcharge_cents": None,
        "line_total_cents": 0,
        "status": "PENDING_APPROVAL",
    })
    calc.refresh_provisional_quote(order)
    touch(order)
    return object_response(selection_view(rec), 201)


@bp.get("/option-selections/<selection_id>")
def read_selection(selection_id):
    auth.require_staff()
    return object_response(selection_view(
        v.fetch(SELECTIONS, selection_id, "ERR_OPTION_SELECTION_NOT_FOUND")))


@bp.get("/option-selections")
def list_selections():
    auth.require_staff()
    rows = v.apply_filters(list(SELECTIONS.values()), [
        ("build_order_id", v.filter_value("build_order_id")),
        ("option_id", v.filter_value("option_id")),
        ("status", v.filter_enum("status", SELECTION_STATUSES)),
    ])
    rows.sort(key=lambda r: (CATALOG[r["option_id"]]["option_code"],
                             r["created_at"], r["_seq"]))
    return paginate(rows, selection_view)


@bp.post("/option-selections/<selection_id>/approve")
def approve_selection(selection_id):
    user_id, _ = auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    sel = v.fetch(SELECTIONS, selection_id, "ERR_OPTION_SELECTION_NOT_FOUND")
    if sel["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_OPTION_SELECTION_STATE_INVALID",
                       "only a PENDING_APPROVAL selection may be approved")
    order = ORDERS.get(sel["build_order_id"])
    if order is not None and order["commercial_status"] not in ("QUOTED",
                                                               "CONFIRMED"):
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "the order is no longer open for option changes")
    if user_id == sel["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the configuring coordinator may not approve the option")
    sel["status"] = "SELECTED"
    touch(sel)
    if order is not None:
        calc.refresh_provisional_quote(order)
        touch(order)
    return object_response(selection_view(sel))


@bp.post("/option-selections/<selection_id>/reject")
def reject_selection(selection_id):
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    v.get_str(body, "reason", required=False)
    sel = v.fetch(SELECTIONS, selection_id, "ERR_OPTION_SELECTION_NOT_FOUND")
    if sel["status"] not in ("PENDING_APPROVAL", "SELECTED"):
        raise ApiError("ERR_OPTION_SELECTION_STATE_INVALID",
                       "the selection is already terminal")
    order = ORDERS.get(sel["build_order_id"])
    if order is not None and order["commercial_status"] not in ("QUOTED",
                                                               "CONFIRMED"):
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "the order is no longer open for option changes")
    sel["status"] = "REJECTED"
    touch(sel)
    if order is not None:
        calc.refresh_provisional_quote(order)
        touch(order)
    return object_response(selection_view(sel))
