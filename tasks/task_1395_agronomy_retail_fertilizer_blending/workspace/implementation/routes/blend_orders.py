"""BlendOrder + BlendLine routes."""

from flask import Blueprint, request, g

import db
from errors import (
    not_found, invalid_transition, validation, business, stale,
    ERR_GROWER_NOT_ORDERABLE, ERR_RECOMMENDATION_NOT_APPROVED,
    ERR_RECOMMENDATION_EXPIRED, ERR_RECOMMENDATION_SUPERSEDED,
    ERR_RECOMMENDATION_FIELD_MISMATCH, ERR_PREPAY_CONTRACT_MISMATCH,
)
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list
from services.core import scaffold_entity, touch, public, lazy_recommendation
from services.orders import (
    recompute_order_provisional, book_order, requote_order, cancel_order,
)
from util import (
    get_body, require, optional, reject_unknown, as_enum, as_number, as_int,
    parse_pagination, paginate, D, one_decimal_max,
)

bp = Blueprint("blend_orders", __name__)

PRICE_MODES = {"FLOATING", "PRICE_LOCKED"}


def _get_grower(gid):
    x = db.growers.get(gid)
    if x is None:
        raise not_found("Grower not found")
    return x


def _get_order(oid):
    x = db.blend_orders.get(oid)
    if x is None:
        raise not_found("Blend order not found")
    return x


def _get_line(lid):
    x = db.blend_lines.get(lid)
    if x is None:
        raise not_found("Blend line not found")
    return x


def _check_recommendation_for_order(rec, field, grower_id):
    """Shared recommendation checks for create/book. Order per §2.7/§3.5:
    NOT_APPROVED (pre-approval), EXPIRED, SUPERSEDED, FIELD_MISMATCH."""
    pass  # implemented inline at call sites to honor per-endpoint ordering


def _order_lines(order_id):
    items = [l for l in db.blend_lines.values() if l["blend_order_id"] == order_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    return items


def _validate_lines_payload(lines_raw):
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise validation("lines must be a non-empty array")
    parsed = []
    for l in lines_raw:
        if not isinstance(l, dict):
            raise validation("each line must be an object")
        for k in l.keys():
            if k not in ("product_id", "target_rate_lbs_per_acre"):
                raise validation(f"Unknown field on line: {k}")
        pid = l.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise validation("line product_id must be a string")
        rate = as_number(l.get("target_rate_lbs_per_acre"), "target_rate_lbs_per_acre",
                         minimum=0, exclusive_min=True)
        rate = one_decimal_max(rate, "target_rate_lbs_per_acre")
        parsed.append({"product_id": pid, "target_rate": rate})
    return parsed


@bp.post("/agronomy/growers/<growerId>/blend-orders")
def create_order(growerId):
    require_roles("Grower", "Agronomist", "BranchAdmin")
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    body = get_body()
    reject_unknown(body, {"field_id", "recommendation_id", "acres", "price_mode",
                          "lines", "prepay_contract_id"})
    field_id = require(body, "field_id")
    rec_id = require(body, "recommendation_id")
    acres = as_number(require(body, "acres"), "acres", minimum=0, exclusive_min=True)
    price_mode = as_enum(require(body, "price_mode"), "price_mode", PRICE_MODES)
    lines_raw = require(body, "lines")
    prepay_contract_id = optional(body, "prepay_contract_id", None)
    parsed_lines = _validate_lines_payload(lines_raw)

    # acres must equal field.acres (body-shape layer check needs the field;
    # field existence is an FK-resolution concern, so resolve FKs first per
    # §2.7 ordering: body shape -> FK resolution; the acres-equality check is
    # listed under body shape but requires the field record. We follow the
    # scaffold's priority 4 wording and validate equality after FK resolution,
    # which is the only point it can be evaluated.)
    field = db.fields.get(field_id)
    if field is None:
        raise not_found("Field not found")
    rec = db.recommendations.get(rec_id)
    if rec is None:
        raise not_found("Recommendation not found")
    contract = None
    if price_mode == "PRICE_LOCKED":
        if prepay_contract_id is None:
            raise validation("prepay_contract_id required when price_mode is PRICE_LOCKED")
        contract = db.prepay_contracts.get(prepay_contract_id)
        if contract is None:
            raise not_found("Prepay contract not found")
    else:
        if prepay_contract_id is not None:
            # PRD: prepay_contract_id required when PRICE_LOCKED, else null
            raise validation("prepay_contract_id must be null when price_mode is FLOATING")
    for pl in parsed_lines:
        if pl["product_id"] not in db.products:
            raise not_found("Product not found")

    # acres == field.acres
    if D(acres) != D(field["acres"]):
        raise validation("acres must equal field.acres")

    # state gates (priority 8 grower-orderable) then business checks
    if grower["credit_status"] != "ACTIVE":
        raise business(ERR_GROWER_NOT_ORDERABLE, 409, "Grower credit status is not ACTIVE")

    # recommendation checks (create-time): NOT_APPROVED -> FIELD_MISMATCH ->
    # SUPERSEDED order per scaffold priorities 26/27/28, EXPIRED at 19 (before those).
    lazy_recommendation(rec)
    if rec["status"] == "EXPIRED":
        raise business(ERR_RECOMMENDATION_EXPIRED, 422, "Recommendation expired")
    if rec["status"] in ("DRAFT", "PENDING_REVIEW"):
        raise business(ERR_RECOMMENDATION_NOT_APPROVED, 422, "Recommendation not approved")
    if rec["field_id"] != field["id"] or field["grower_id"] != grower["id"]:
        raise business(ERR_RECOMMENDATION_FIELD_MISMATCH, 422,
                       "Recommendation field differs from order field or field not owned by grower")
    if rec["status"] == "SUPERSEDED":
        raise business(ERR_RECOMMENDATION_SUPERSEDED, 422, "Recommendation superseded")

    # PRICE_LOCKED contract matching
    if price_mode == "PRICE_LOCKED":
        ok = (
            contract["grower_id"] == grower["id"]
            and contract["status"] == "FUNDED"
            and any(pl["product_id"] == contract["product_id"] for pl in parsed_lines)
            and (contract["funded_cents"] - contract["drawn_cents"]) > 0
        )
        if not ok:
            raise business(ERR_PREPAY_CONTRACT_MISMATCH, 422, "Prepay contract mismatch")

    # create the order + lines
    order = scaffold_entity(db.blend_orders, {
        "grower_id": grower["id"],
        "field_id": field["id"],
        "recommendation_id": rec["id"],
        "prepay_contract_id": prepay_contract_id,
        "acres": float(acres),
        "price_mode": price_mode,
        "tons_total": 0,
        "n_lbs_per_acre": 0,
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "rebate_cents": 0,
        "invoiced_at": None,
        "fulfillment_status": "QUOTED",
        "payment_status": "UNPAID",
    })
    order["_invoiced_at"] = None
    for pl in parsed_lines:
        scaffold_entity(db.blend_lines, {
            "blend_order_id": order["id"],
            "product_id": pl["product_id"],
            "target_rate_lbs_per_acre": float(pl["target_rate"]),
            "actual_rate_lbs_per_acre": None,
            "quantity_tons": 0,
            "actual_quantity_tons": None,
            "unit_price_cents": 0,
            "line_provisional_cents": 0,
            "final_unit_price_cents": None,
            "line_final_cents": None,
            "variance_flag": False,
        })
    recompute_order_provisional(order, touch_lines=False)
    # Creation scaffolds order+lines at version 1 with computed values — no
    # mutation has happened yet, so no touch() here (PRD 2.4: version bumps
    # only on mutation).
    return success_object(public(order), 201)


@bp.get("/agronomy/growers/<growerId>/blend-orders")
def list_grower_orders(growerId):
    require_roles(*ALL_ROLES)
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    limit, offset = parse_pagination()
    items = [o for o in db.blend_orders.values() if o["grower_id"] == grower["id"]]
    if "fulfillment_status" in request.args:
        items = [o for o in items if o["fulfillment_status"] == request.args["fulfillment_status"]]
    if "payment_status" in request.args:
        items = [o for o in items if o["payment_status"] == request.args["payment_status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/blend-orders")
def list_orders():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.blend_orders.values())
    for f in ("grower_id", "field_id", "recommendation_id", "prepay_contract_id",
              "fulfillment_status", "payment_status"):
        if f in request.args:
            items = [o for o in items if o.get(f) == request.args[f]]
    if g.role == "Grower":
        items = [o for o in items if o["grower_id"] == g.user_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/blend-orders/<orderId>")
def get_order(orderId):
    require_roles(*ALL_ROLES)
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    return success_object(public(order))


@bp.patch("/agronomy/blend-orders/<orderId>")
def patch_order(orderId):
    require_roles("Grower", "Agronomist")
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    body = get_body()
    reject_unknown(body, {"expected_blend_order_version", "acres", "price_mode",
                          "prepay_contract_id", "lines"})
    expected = as_int(require(body, "expected_blend_order_version"),
                      "expected_blend_order_version", minimum=0)
    acres = optional(body, "acres", None)
    price_mode = optional(body, "price_mode", None)
    prepay_contract_id_present = "prepay_contract_id" in body
    prepay_contract_id = body.get("prepay_contract_id")
    lines_raw = optional(body, "lines", None)

    new_acres = None
    if acres is not None:
        new_acres = as_number(acres, "acres", minimum=0, exclusive_min=True)
    new_price_mode = None
    if price_mode is not None:
        new_price_mode = as_enum(price_mode, "price_mode", PRICE_MODES)
    parsed_lines = None
    if lines_raw is not None:
        parsed_lines = _validate_lines_payload(lines_raw)

    # FK resolution
    if parsed_lines is not None:
        for pl in parsed_lines:
            if pl["product_id"] not in db.products:
                raise not_found("Product not found")
    new_contract = None
    if prepay_contract_id_present and prepay_contract_id is not None:
        new_contract = db.prepay_contracts.get(prepay_contract_id)
        if new_contract is None:
            raise not_found("Prepay contract not found")

    # OCC
    if expected != order["version"]:
        raise stale("expected_blend_order_version does not match order version")

    # state
    if order["fulfillment_status"] != "QUOTED":
        raise invalid_transition("Only QUOTED orders may be updated")

    # apply
    if new_acres is not None:
        if D(new_acres) != D(db.fields[order["field_id"]]["acres"]):
            raise validation("acres must equal field.acres")
        order["acres"] = float(new_acres)
    if new_price_mode is not None:
        order["price_mode"] = new_price_mode
    if prepay_contract_id_present:
        order["prepay_contract_id"] = prepay_contract_id
    if order["price_mode"] == "PRICE_LOCKED" and not order.get("prepay_contract_id"):
        raise validation("prepay_contract_id required when price_mode is PRICE_LOCKED")
    if order["price_mode"] == "FLOATING" and order.get("prepay_contract_id") is not None:
        # keep strictness: FLOATING orders carry null contract
        order["prepay_contract_id"] = None

    if parsed_lines is not None:
        # replace lines
        for lid in [l["id"] for l in _order_lines(order["id"])]:
            del db.blend_lines[lid]
        for pl in parsed_lines:
            scaffold_entity(db.blend_lines, {
                "blend_order_id": order["id"],
                "product_id": pl["product_id"],
                "target_rate_lbs_per_acre": float(pl["target_rate"]),
                "actual_rate_lbs_per_acre": None,
                "quantity_tons": 0,
                "actual_quantity_tons": None,
                "unit_price_cents": 0,
                "line_provisional_cents": 0,
                "final_unit_price_cents": None,
                "line_final_cents": None,
                "variance_flag": False,
            })
    recompute_order_provisional(order, touch_lines=False)
    touch(order)
    return success_object(public(order))


@bp.post("/agronomy/blend-orders/<orderId>/book")
def book(orderId):
    require_roles("Grower", "Agronomist")
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    if order["fulfillment_status"] != "QUOTED":
        raise invalid_transition("Order not QUOTED")
    book_order(order)
    return success_object(public(order))


@bp.post("/agronomy/blend-orders/<orderId>/requote")
def requote(orderId):
    require_roles("Grower", "Agronomist")
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    if order["fulfillment_status"] != "BOOKED":
        raise invalid_transition("Order not BOOKED")
    requote_order(order)
    return success_object(public(order))


@bp.post("/agronomy/blend-orders/<orderId>/cancel")
def cancel(orderId):
    require_roles("Grower", "Agronomist")
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    body = get_body()
    reject_unknown(body, {"reason"})
    if order["fulfillment_status"] not in ("QUOTED", "BOOKED", "SCHEDULED"):
        raise invalid_transition("Order not in QUOTED, BOOKED or SCHEDULED")
    cancel_order(order)
    return success_object(public(order))


@bp.post("/agronomy/blend-orders/<orderId>/confirm-application")
def confirm_application(orderId):
    require_roles("Grower")
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    if order["fulfillment_status"] != "DELIVERED":
        raise invalid_transition("Order not DELIVERED")
    order["fulfillment_status"] = "APPLIED_CONFIRMED"
    if order["payment_status"] == "PAID":
        order["fulfillment_status"] = "CLOSED"
        grower = db.growers[order["grower_id"]]
        from services.core import recompute_season_closed_tons
        recompute_season_closed_tons(grower)
        touch(grower)
    touch(order)
    return success_object(public(order))


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

@bp.get("/agronomy/blend-orders/<orderId>/lines")
def list_order_lines(orderId):
    require_roles(*ALL_ROLES)
    order = _get_order(orderId)
    check_grower_ownership(order["grower_id"])
    limit, offset = parse_pagination()
    items = _order_lines(order["id"])
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/blend-lines/<lineId>")
def get_line(lineId):
    require_roles(*ALL_ROLES)
    line = _get_line(lineId)
    order = db.blend_orders.get(line["blend_order_id"])
    if order is not None:
        check_grower_ownership(order["grower_id"])
    return success_object(public(line))


@bp.get("/agronomy/blend-lines")
def list_lines():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.blend_lines.values())
    if "product_id" in request.args:
        items = [l for l in items if l["product_id"] == request.args["product_id"]]
    if "blend_order_id" in request.args:
        items = [l for l in items if l["blend_order_id"] == request.args["blend_order_id"]]
    if g.role == "Grower":
        items = [l for l in items
                 if db.blend_orders.get(l["blend_order_id"], {}).get("grower_id") == g.user_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)
