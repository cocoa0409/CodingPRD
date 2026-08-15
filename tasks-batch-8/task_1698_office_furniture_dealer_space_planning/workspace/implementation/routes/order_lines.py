"""OrderLine routes: add lines to DRAFT orders, cancel lines while DRAFT.

Gate order at creation (PRD 3.4): series quality hold (5b) -> discontinued
series (7c) -> typical-to-plan linkage (7b) -> structural shape (8a).
"""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SERIES_ON_QUALITY_HOLD,
    ERR_SERIES_DISCONTINUED,
    ERR_TYPICAL_PLAN_MISMATCH,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch, recompute_order_totals
from services.pricing import price_line, selected_option_entries
from validate import body_dict, req_str, req_int, req_list, is_int

bp = Blueprint("order_lines", __name__)


@bp.route("/api/order-lines", methods=["POST"])
def create_order_line():
    authorize(["AccountExecutive"])
    body = body_dict()
    order_id = req_str(body, "order_id")
    series_id = req_str(body, "series_id")
    typical_id = body.get("typical_id")
    if typical_id is not None and not isinstance(typical_id, str):
        raise_error(ERR_INVALID_REQUEST, "typical_id must be a string")
    # priority 3: FK existence
    order = get_or_404("project_orders", order_id)
    series = get_or_404("product_series", series_id)
    typical = None
    if typical_id is not None:
        typical = get_or_404("typicals", typical_id)
    # priority 4: lines may be added only while the order is DRAFT
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot add lines to an order in status {order['status']}")
    # priority 5b: quality hold blocks new lines
    if series.get("quality_hold"):
        raise_error(ERR_SERIES_ON_QUALITY_HOLD, f"series {series_id} is on quality hold")
    # priority 7c: discontinued series blocked (PRD 3.4 gate order)
    if series["status"] == "DISCONTINUED":
        raise_error(ERR_SERIES_DISCONTINUED, f"series {series_id} is DISCONTINUED")
    # priority 7b: typical must belong to the order's space plan
    if typical is not None and typical["space_plan_id"] != order["space_plan_id"]:
        raise_error(ERR_TYPICAL_PLAN_MISMATCH,
                    f"typical {typical_id} does not belong to plan {order['space_plan_id']}")
    # priority 8a: field shape, range, and option-code validity
    quantity = req_int(body, "quantity", minv=1)
    selected_options = req_list(body, "selected_options")
    for code in selected_options:
        if not isinstance(code, str):
            raise_error(ERR_INVALID_REQUEST, "selected_options entries must be strings")
    selected_option_entries(series, selected_options)  # unknown option codes -> 400
    contract = get_or_404("pricing_contracts", order["contract_id"])
    line = new_entity("order_lines", {
        "order_id": order_id,
        "series_id": series_id,
        "typical_id": typical_id,
        "quantity": quantity,
        "selected_options": selected_options,
        "is_replacement": False,
        "unit_list_price_cents": 0,
        "unit_net_price_cents": 0,
        "line_total_cents": 0,
        "provisional_lead_time_days": None,
        "provisional_promise_date": None,
        "confirmed_lead_time_days": None,
        "confirmed_promise_date": None,
        "received_units": 0,
        "status": "OPEN",
    })
    price_line(line, series, contract)
    recompute_order_totals(order)
    return success_object(public(line), status=201)


@bp.route("/api/order-lines", methods=["GET"])
def list_order_lines():
    authorize(ALL_ROLES)
    return list_response("order_lines", ["order_id", "series_id", "typical_id", "status"])


@bp.route("/api/order-lines/<line_id>", methods=["GET"])
def get_order_line(line_id):
    authorize(ALL_ROLES)
    return get_response("order_lines", line_id)


@bp.route("/api/order-lines/<line_id>/cancel", methods=["POST"])
def cancel_order_line(line_id):
    authorize(["AccountExecutive"])
    line = get_or_404("order_lines", line_id)
    order = get_or_404("project_orders", line["order_id"])
    # priority 4: the transition exists from OPEN while the parent order is DRAFT
    if line["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, f"cannot cancel a line in status {line['status']}")
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot cancel a line while the order is {order['status']}")
    line["status"] = "CANCELLED"
    touch(line)
    recompute_order_totals(order)
    return success_object(public(line))
