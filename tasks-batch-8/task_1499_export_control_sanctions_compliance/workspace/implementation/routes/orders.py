"""Export order endpoints: intake, submit (screening + final determination),
hold release, license attachment, release, cancel."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CLASSIFICATION_REQUIRED,
    ERR_DESTINATION_EMBARGOED,
    ERR_INVALID_STATE,
    ERR_VALIDATION,
    ERR_LICENSE_NOT_REQUIRED,
    ERR_LICENSE_PRODUCT_MISMATCH,
    ERR_LICENSE_REQUIRED,
    ERR_LICENSE_WINDOW_INVALID,
    ERR_ORDER_PROHIBITED,
    ERR_PARTY_BLOCKED,
    ERR_SCREENING_REVIEW_PENDING,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_int,
    v_enum,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.determination import (
    destination_embargoed,
    determine,
    active_classification,
    order_totals,
)
from services.screening import run_screening
from services.audit import write_audit

bp = Blueprint("orders", __name__)

END_USES = ("CIVILIAN", "MILITARY", "DUAL_USE")


def _window_covers_today(license_):
    today = db.today()
    return license_["valid_from"] <= today <= license_["valid_until"]


@bp.post("/compliance/orders")
def create_order():
    auth("TradeOpsSpecialist")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("product_id", db.PRODUCTS), ("party_id", db.PARTIES)))
    # Priority 4: request shape
    no_unknown(body, {"product_id", "party_id", "destination_country", "end_use", "quantity"})
    product_id = v_str(need(body, "product_id"), "product_id")
    party_id = v_str(need(body, "party_id"), "party_id")
    destination = v_str(need(body, "destination_country"), "destination_country")
    end_use = v_enum(need(body, "end_use"), "end_use", END_USES)
    quantity = v_int(need(body, "quantity"), "quantity")
    if quantity <= 0:
        raise ApiError(ERR_VALIDATION, "quantity must be > 0", 400)
    product = find(db.PRODUCTS, product_id, "Product")
    party = find(db.PARTIES, party_id, "Party")
    # Priority 7: destination embargo guard
    if destination_embargoed(destination):
        raise ApiError(
            ERR_DESTINATION_EMBARGOED,
            "Destination country %s is under a PROHIBITED embargo" % destination,
            409,
        )
    # Priority 8: provisional determination requires an ACTIVE classification
    if product["status"] != "CLASSIFIED":
        raise ApiError(
            ERR_CLASSIFICATION_REQUIRED,
            "Product %s has no ACTIVE classification" % product_id,
            409,
        )
    goods, surcharge, total = order_totals(quantity, product["unit_value_cents"])
    provisional = determine(product, party, destination, end_use)
    order = {
        "product_id": product_id,
        "party_id": party_id,
        "destination_country": destination,
        "end_use": end_use,
        "quantity": quantity,
        "license_id": None,
        "provisional_determination": provisional,
        "determination": None,
        "determination_classification_sequence": None,
        "goods_value_cents": goods,
        "surcharge_cents": surcharge,
        "total_value_cents": total,
        "accumulated_fees_cents": 0,
        "shipped_quantity": 0,
        "pre_hold_status": None,
        "status": "DRAFT",
    }
    db.stamp_new(order)
    db.ORDERS[order["id"]] = order
    return ok(db.pub(order), "object", 201)


@bp.get("/compliance/orders/<oid>")
def get_order(oid):
    auth()
    order = find(db.ORDERS, oid, "ExportOrder")
    return ok(db.pub(order), "object", 200)


@bp.get("/compliance/orders")
def list_orders():
    auth()
    filters = {
        "product_id": request.args.get("product_id"),
        "party_id": request.args.get("party_id"),
        "license_id": request.args.get("license_id"),
        "status": request.args.get("status"),
    }
    items = filtered_sorted(db.ORDERS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/orders/<oid>/submit")
def submit_order(oid):
    auth("TradeOpsSpecialist")
    order = find(db.ORDERS, oid, "ExportOrder")
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Order is not DRAFT", 409)
    product = find(db.PRODUCTS, order["product_id"], "Product")
    if product["status"] != "CLASSIFIED":
        raise ApiError(
            ERR_CLASSIFICATION_REQUIRED,
            "Product %s has no ACTIVE classification" % product["id"],
            409,
        )
    party = find(db.PARTIES, order["party_id"], "Party")
    # 1) ORDER-context screening, EXACT variant; posture recomputed
    result = run_screening(party, "ORDER", "EXACT")
    # 2) final determination pinned against the ACTIVE classification
    determination = determine(product, party, order["destination_country"], order["end_use"])
    classification = active_classification(product)
    order["determination"] = determination
    order["determination_classification_sequence"] = classification["sequence"]
    # 3) auto-continue out of IN_REVIEW
    if result["status"] == "CLEAR" and determination != "PROHIBITED":
        order["status"] = "CLEARED"
    else:
        order["status"] = "HELD"
        order["pre_hold_status"] = None  # review hold returns to CLEARED
    db.touch(order)
    return ok(db.pub(order), "object", 200)


@bp.post("/compliance/orders/<oid>/release-hold")
def release_hold(oid):
    auth("ComplianceManager")
    order = find(db.ORDERS, oid, "ExportOrder")
    if order["status"] != "HELD":
        raise ApiError(ERR_INVALID_STATE, "Order is not HELD", 409)
    party = find(db.PARTIES, order["party_id"], "Party")
    if party["screening_posture"] == "REVIEW_REQUIRED":
        raise ApiError(
            ERR_SCREENING_REVIEW_PENDING,
            "Party %s has an unresolved POTENTIAL_MATCH" % party["id"],
            409,
        )
    if party["screening_posture"] == "BLOCKED":
        raise ApiError(ERR_PARTY_BLOCKED, "Party %s is BLOCKED" % party["id"], 409)
    if order["determination"] == "PROHIBITED":
        raise ApiError(ERR_ORDER_PROHIBITED, "Order determination is PROHIBITED", 409)
    if order["pre_hold_status"] == "LICENSED":
        license_ = find(db.LICENSES, order["license_id"], "License")
        if license_["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Attached license is not APPROVED", 409)
        if not _window_covers_today(license_):
            raise ApiError(
                ERR_LICENSE_WINDOW_INVALID,
                "License validity window does not cover the current date",
                409,
            )
    order["status"] = order["pre_hold_status"] if order["pre_hold_status"] else "CLEARED"
    order["pre_hold_status"] = None
    db.touch(order)
    return ok(db.pub(order), "object", 200)


@bp.post("/compliance/orders/<oid>/attach-license")
def attach_license(oid):
    auth("TradeOpsSpecialist")
    order = find(db.ORDERS, oid, "ExportOrder")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("license_id", db.LICENSES),))
    no_unknown(body, {"license_id"})
    license_id = v_str(need(body, "license_id"), "license_id")
    license_ = find(db.LICENSES, license_id, "License")
    # Priority 6: state (order from-state, attached-license APPROVED)
    if order["status"] != "CLEARED":
        raise ApiError(ERR_INVALID_STATE, "Order is not CLEARED", 409)
    if license_["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "License is not APPROVED", 409)
    # Priority 8: structural compliance
    if order["determination"] != "LICENSE_REQUIRED":
        raise ApiError(
            ERR_LICENSE_NOT_REQUIRED, "Order determination is not LICENSE_REQUIRED", 409
        )
    # Priority 9: cross-entity referential consistency
    if license_["product_id"] != order["product_id"]:
        raise ApiError(
            ERR_LICENSE_PRODUCT_MISMATCH,
            "License product does not match order product",
            409,
        )
    if not _window_covers_today(license_):
        raise ApiError(
            ERR_LICENSE_WINDOW_INVALID,
            "License validity window does not cover the current date",
            409,
        )
    order["license_id"] = license_id
    order["status"] = "LICENSED"
    db.touch(order)
    return ok(db.pub(order), "object", 200)


@bp.post("/compliance/orders/<oid>/release")
def release_order(oid):
    uid, role = auth("TradeOpsSpecialist")
    order = find(db.ORDERS, oid, "ExportOrder")
    if order["status"] == "CLEARED":
        if order["determination"] != "NOT_REQUIRED":
            raise ApiError(
                ERR_LICENSE_REQUIRED,
                "Order determination requires an attached license",
                409,
            )
    elif order["status"] == "LICENSED":
        license_ = find(db.LICENSES, order["license_id"], "License")
        if license_["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Attached license is not APPROVED", 409)
        if not _window_covers_today(license_):
            raise ApiError(
                ERR_LICENSE_WINDOW_INVALID,
                "License validity window does not cover the current date",
                409,
            )
    else:
        raise ApiError(ERR_INVALID_STATE, "Order is not CLEARED or LICENSED", 409)
    order["status"] = "RELEASED"
    db.touch(order)
    write_audit("ORDER_RELEASED", "ExportOrder", order["id"], role, uid, "Order %s released" % order["id"])
    return ok(db.pub(order), "object", 200)


@bp.post("/compliance/orders/<oid>/cancel")
def cancel_order(oid):
    auth("TradeOpsSpecialist")
    order = find(db.ORDERS, oid, "ExportOrder")
    if order["status"] not in ("DRAFT", "IN_REVIEW", "CLEARED", "HELD"):
        raise ApiError(ERR_INVALID_STATE, "Order cannot be cancelled from %s" % order["status"], 409)
    order["status"] = "CANCELLED"
    db.touch(order)
    return ok(db.pub(order), "object", 200)
