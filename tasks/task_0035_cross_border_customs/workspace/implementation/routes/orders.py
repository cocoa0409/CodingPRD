"""Order endpoints."""

from flask import Blueprint, g

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    forbidden,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.common import get_body, stamp_create, touch, check_occ
from services.serializers import serialize_order


bp = Blueprint("orders", __name__)


@bp.route("/orders", methods=["POST"])
@require_roles("Declarant")
def create_order():
    body = get_body()
    required = ["external_order_ref", "importer_id", "declarant_id", "trade_mode",
                "origin_country", "destination_country", "currency", "line_items",
                "total_value_minor"]
    for f in required:
        if f not in body:
            raise APIError(ERR_INVALID_REQUEST, f"{f} required", 400)

    trade_mode = body["trade_mode"]
    if trade_mode not in ("B2C_DIRECT_MAIL", "BONDED_WAREHOUSE", "GENERAL_TRADE"):
        raise APIError(ERR_INVALID_REQUEST, "Invalid trade_mode", 400)

    line_items = body["line_items"]
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise APIError(ERR_INVALID_REQUEST, "line_items must be a non-empty array", 400)
    for li in line_items:
        if not isinstance(li, dict):
            raise APIError(ERR_INVALID_REQUEST, "line_items entries must be objects", 400)
        for k in ("product_description", "quantity", "unit_price", "weight_kg"):
            if k not in li:
                raise APIError(ERR_INVALID_REQUEST, f"line_items.{k} required", 400)
        if not isinstance(li["quantity"], int) or li["quantity"] < 0 or isinstance(li["quantity"], bool):
            raise APIError(ERR_INVALID_REQUEST, "line_items.quantity must be non-negative integer", 400)
        if not isinstance(li["unit_price"], int) or li["unit_price"] < 0 or isinstance(li["unit_price"], bool):
            raise APIError(ERR_INVALID_REQUEST, "line_items.unit_price must be non-negative integer", 400)

    total_value_minor = body["total_value_minor"]
    if not isinstance(total_value_minor, int) or isinstance(total_value_minor, bool):
        raise APIError(ERR_INVALID_REQUEST, "total_value_minor must be integer", 400)

    with LOCK:
        if body["importer_id"] not in DB.importers:
            raise not_found("Importer not found")
        if body["declarant_id"] not in DB.declarants:
            raise not_found("Declarant not found")

        # Uniqueness on (importer_id, external_order_ref)
        for od in DB.orders.values():
            if (od["importer_id"] == body["importer_id"]
                    and od["external_order_ref"] == body["external_order_ref"]):
                raise APIError(ERR_INVALID_REQUEST, "external_order_ref already exists for this importer", 400)

        order = {
            "external_order_ref": body["external_order_ref"],
            "importer_id": body["importer_id"],
            "declarant_id": body["declarant_id"],
            "trade_mode": trade_mode,
            "origin_country": body["origin_country"],
            "destination_country": body["destination_country"],
            "currency": body["currency"],
            "line_items": list(line_items),
            "total_value_minor": int(total_value_minor),
            "status": "PENDING_DECLARATION",
        }
        stamp_create(order)
        DB.orders[order["id"]] = order
        return success_object(serialize_order(order), status=201)


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
@require_roles("Importer")
def cancel_order(order_id):
    body = get_body()
    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found("Order not found")
        # Ownership: importer's X-User-ID must match order.importer_id
        if order["importer_id"] != g.user_id:
            raise forbidden("Importer does not own this order")
        if order["status"] != "PENDING_DECLARATION":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Order can only be cancelled from PENDING_DECLARATION", 409)

        # Look up child declarations for this order
        related = [d for d in DB.declarations.values() if d["order_id"] == order_id]
        # Allowed if no declaration exists, or only DRAFT
        for d in related:
            if d["status"] != "DRAFT":
                raise APIError(ERR_INVALID_STATE_TRANSITION,
                               "Cannot cancel: declaration exists past DRAFT", 409)
        check_occ(order, body)
        # Delete DRAFT declarations + their lines
        for d in related:
            if d["status"] == "DRAFT":
                # Remove lines
                for ln_id in list(DB.declaration_lines.keys()):
                    if DB.declaration_lines[ln_id]["declaration_id"] == d["id"]:
                        del DB.declaration_lines[ln_id]
                del DB.declarations[d["id"]]
        order["status"] = "CANCELLED"
        touch(order)
        return success_object(serialize_order(order), status=200)


@bp.route("/orders/<order_id>/return", methods=["POST"])
@require_roles("Importer")
def return_order(order_id):
    body = get_body()
    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found("Order not found")
        if order["importer_id"] != g.user_id:
            raise forbidden("Importer does not own this order")
        if order["status"] not in ("DECLARED", "RELEASED"):
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Order can only be returned from DECLARED or RELEASED", 409)
        # No EXECUTED Refund against this order's declaration's payment notice
        related_decs = [d for d in DB.declarations.values() if d["order_id"] == order_id]
        for d in related_decs:
            for rf in DB.refunds.values():
                if rf["declaration_id"] == d["id"] and rf["status"] == "EXECUTED":
                    raise APIError(ERR_INVALID_STATE_TRANSITION,
                                   "Cannot return: an EXECUTED Refund exists", 409)
        check_occ(order, body)
        order["status"] = "RETURNED"
        touch(order)
        return success_object(serialize_order(order), status=200)


@bp.route("/orders/<order_id>", methods=["GET"])
@require_roles("Declarant", "CustomsOfficer", "Importer", "Auditor")
def get_order(order_id):
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("Order not found")
    if g.role == "Importer" and order["importer_id"] != g.user_id:
        raise forbidden("Importer does not own this order")
    return success_object(serialize_order(order), status=200)
