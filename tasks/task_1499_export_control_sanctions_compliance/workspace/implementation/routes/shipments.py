"""Shipment endpoints: planning, screening, release (license consumption
ledger + per-shipment fee), and in-transit event advances."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_LICENSE_CONDITION_VIOLATION,
    ERR_LICENSE_QUANTITY_INSUFFICIENT,
    ERR_LICENSE_VALUE_INSUFFICIENT,
    ERR_LICENSE_WINDOW_INVALID,
    ERR_ORDER_QUANTITY_EXCEEDED,
    ERR_PARTY_BLOCKED,
    ERR_SCREENING_REVIEW_PENDING,
    ERR_VALIDATION,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_int,
    v_date,
    v_enum,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.determination import shipment_fee
from services.screening import run_screening
from services.cascade import (
    maybe_close_order,
    check_license_exhausted,
    check_license_reactivation,
)
from services.audit import write_audit

bp = Blueprint("shipments", __name__)

# Statuses that consume the order's quantity budget
_BUDGET_STATUSES = ("PLANNED", "SCREENED", "HELD", "RELEASED", "IN_TRANSIT", "DELIVERED")


def _window_covers_today(license_):
    today = db.today()
    return license_["valid_from"] <= today <= license_["valid_until"]


@bp.post("/compliance/shipments")
def create_shipment():
    auth("TradeOpsSpecialist")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("order_id", db.ORDERS),))
    # Priority 4: request shape
    no_unknown(body, {"order_id", "quantity", "planned_ship_date"})
    order_id = need(body, "order_id")
    if not isinstance(order_id, str):
        raise ApiError(ERR_VALIDATION, "order_id must be a string", 400)
    quantity = v_int(need(body, "quantity"), "quantity")
    if quantity <= 0:
        raise ApiError(ERR_VALIDATION, "quantity must be > 0", 400)
    planned_date = v_date(need(body, "planned_ship_date"), "planned_ship_date")
    order = find(db.ORDERS, order_id, "ExportOrder")
    # Priority 6: parent order must be LICENSED or RELEASED
    if order["status"] not in ("LICENSED", "RELEASED"):
        raise ApiError(
            ERR_INVALID_STATE, "Parent order is not LICENSED or RELEASED", 409
        )
    # Priority 10: order quantity budget
    committed = sum(
        s["quantity"]
        for s in db.SHIPMENTS.values()
        if s["order_id"] == order["id"] and s["status"] in _BUDGET_STATUSES
    )
    if committed + quantity > order["quantity"]:
        raise ApiError(
            ERR_ORDER_QUANTITY_EXCEEDED,
            "Shipment would exceed the order's quantity budget",
            409,
        )
    shipment = {
        "order_id": order["id"],
        "quantity": quantity,
        "planned_ship_date": planned_date,
        "screening_result_id": None,
        "consumed_value_cents": 0,
        "fee_cents": 0,
        "status": "PLANNED",
    }
    db.stamp_new(shipment)
    db.SHIPMENTS[shipment["id"]] = shipment
    return ok(db.pub(shipment), "object", 201)


@bp.get("/compliance/shipments/<sid>")
def get_shipment(sid):
    auth()
    shipment = find(db.SHIPMENTS, sid, "Shipment")
    return ok(db.pub(shipment), "object", 200)


@bp.get("/compliance/shipments")
def list_shipments():
    auth()
    filters = {
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
    }
    items = filtered_sorted(db.SHIPMENTS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/shipments/<sid>/screen")
def screen_shipment(sid):
    auth("TradeOpsSpecialist")
    shipment = find(db.SHIPMENTS, sid, "Shipment")
    if shipment["status"] not in ("PLANNED", "HELD"):
        raise ApiError(ERR_INVALID_STATE, "Shipment is not PLANNED or HELD", 409)
    order = find(db.ORDERS, shipment["order_id"], "ExportOrder")
    party = find(db.PARTIES, order["party_id"], "Party")
    result = run_screening(party, "SHIPMENT", "FUZZY")
    shipment["screening_result_id"] = result["id"]
    shipment["status"] = "SCREENED" if result["status"] == "CLEAR" else "HELD"
    db.touch(shipment)
    return ok(db.pub(result), "object", 201)


@bp.post("/compliance/shipments/<sid>/release")
def release_shipment(sid):
    uid, role = auth("TradeOpsSpecialist")
    shipment = find(db.SHIPMENTS, sid, "Shipment")
    # Priority 6: state preconditions (shipment, parent order, attached license)
    if shipment["status"] != "SCREENED":
        raise ApiError(ERR_INVALID_STATE, "Shipment is not SCREENED", 409)
    order = find(db.ORDERS, shipment["order_id"], "ExportOrder")
    if order["status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, "Parent order is not RELEASED", 409)
    license_ = None
    if order["license_id"] is not None:
        license_ = find(db.LICENSES, order["license_id"], "License")
        if license_["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Attached license is not APPROVED", 409)
    # Priority 7: sanctions safety
    party = find(db.PARTIES, order["party_id"], "Party")
    if party["screening_posture"] == "BLOCKED":
        raise ApiError(ERR_PARTY_BLOCKED, "Party %s is BLOCKED" % party["id"], 409)
    if party["screening_posture"] == "REVIEW_REQUIRED":
        raise ApiError(
            ERR_SCREENING_REVIEW_PENDING,
            "Party %s has an unresolved POTENTIAL_MATCH" % party["id"],
            409,
        )
    if (
        license_ is not None
        and "NO_MILITARY_END_USE" in license_["conditions"]
        and order["end_use"] == "MILITARY"
    ):
        raise ApiError(
            ERR_LICENSE_CONDITION_VIOLATION,
            "License carries NO_MILITARY_END_USE but order end_use is MILITARY",
            409,
        )
    product = find(db.PRODUCTS, order["product_id"], "Product")
    consumed = shipment["quantity"] * product["unit_value_cents"]
    # Priority 9: license validity window
    if license_ is not None and not _window_covers_today(license_):
        raise ApiError(
            ERR_LICENSE_WINDOW_INVALID,
            "License validity window does not cover the current date",
            409,
        )
    # Priority 10: fiscal sufficiency (inclusive comparisons; equality exhausts)
    if license_ is not None:
        if shipment["quantity"] > license_["remaining_quantity"]:
            raise ApiError(
                ERR_LICENSE_QUANTITY_INSUFFICIENT,
                "Shipment quantity exceeds license remaining_quantity",
                409,
            )
        if consumed > license_["remaining_value_cents"]:
            raise ApiError(
                ERR_LICENSE_VALUE_INSUFFICIENT,
                "Shipment value exceeds license remaining_value_cents",
                409,
            )
    # Effects: shipment computed fields, license ledger, order accumulators
    fee = shipment_fee(consumed)
    shipment["consumed_value_cents"] = consumed
    shipment["fee_cents"] = fee
    shipment["status"] = "RELEASED"
    db.touch(shipment)
    if license_ is not None:
        license_["remaining_quantity"] -= shipment["quantity"]
        license_["remaining_value_cents"] -= consumed
        license_["consumed_quantity"] += shipment["quantity"]
        license_["consumed_value_cents"] += consumed
        db.touch(license_)
        check_license_exhausted(license_)
    order["accumulated_fees_cents"] += fee
    order["shipped_quantity"] += shipment["quantity"]
    db.touch(order)
    write_audit(
        "SHIPMENT_RELEASED", "Shipment", shipment["id"], role, uid,
        "Shipment %s released" % shipment["id"],
    )
    return ok(db.pub(shipment), "object", 200)


@bp.post("/compliance/shipments/<sid>/advance")
def advance_shipment(sid):
    uid, role = auth("TradeOpsSpecialist")
    shipment = find(db.SHIPMENTS, sid, "Shipment")
    body = get_body()
    no_unknown(body, {"event"})
    event = v_enum(need(body, "event"), "event", ("DEPART", "DELIVER", "RETURN", "CANCEL"))
    order = find(db.ORDERS, shipment["order_id"], "ExportOrder")
    if event == "DEPART":
        if shipment["status"] != "RELEASED":
            raise ApiError(ERR_INVALID_STATE, "DEPART requires RELEASED", 409)
        shipment["status"] = "IN_TRANSIT"
        db.touch(shipment)
    elif event == "DELIVER":
        if shipment["status"] != "IN_TRANSIT":
            raise ApiError(ERR_INVALID_STATE, "DELIVER requires IN_TRANSIT", 409)
        shipment["status"] = "DELIVERED"
        db.touch(shipment)
        maybe_close_order(order)
    elif event == "RETURN":
        if shipment["status"] != "IN_TRANSIT":
            raise ApiError(ERR_INVALID_STATE, "RETURN requires IN_TRANSIT", 409)
        shipment["status"] = "RETURNED"
        db.touch(shipment)
        # Unwind the license ledger by exactly the released amounts
        if order["license_id"] is not None:
            license_ = find(db.LICENSES, order["license_id"], "License")
            license_["remaining_quantity"] += shipment["quantity"]
            license_["remaining_value_cents"] += shipment["consumed_value_cents"]
            license_["consumed_quantity"] -= shipment["quantity"]
            license_["consumed_value_cents"] -= shipment["consumed_value_cents"]
            db.touch(license_)
            check_license_reactivation(license_)
        order["shipped_quantity"] -= shipment["quantity"]
        db.touch(order)
        write_audit(
            "SHIPMENT_RETURNED", "Shipment", shipment["id"], role, uid,
            "Shipment %s returned" % shipment["id"],
        )
        maybe_close_order(order)
    else:  # CANCEL
        if shipment["status"] not in ("PLANNED", "SCREENED", "HELD"):
            raise ApiError(
                ERR_INVALID_STATE, "CANCEL requires PLANNED, SCREENED, or HELD", 409
            )
        shipment["status"] = "CANCELLED"
        db.touch(shipment)
        maybe_close_order(order)
    return ok(db.pub(shipment), "object", 200)
