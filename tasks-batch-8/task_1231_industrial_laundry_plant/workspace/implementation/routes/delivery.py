"""Delivery and Discrepancy endpoints."""

from flask import Blueprint

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_STOP_NOT_PICKED_UP,
    ERR_CARTS_PENDING,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_STALE_VERSION,
    ERR_NO_SHORTAGE,
    ERR_INVALID_APPROVED_QUANTITY,
    ERR_INVOICE_NOT_DRAFT,
    ERR_INVOICE_CUSTOMER_MISMATCH,
)
from response import success, list_response
from util import (
    ALL_ROLES,
    authenticate,
    require_roles,
    cc_owns,
    body_json,
    field,
    path_get,
    ref_get,
    round0,
    D,
)

bp = Blueprint("delivery", __name__)


def _delivery_customer(delivery):
    stop = db.stops.get(delivery["stop_id"])
    return stop["customer_id"] if stop else None


def _discrepancy_customer(disc):
    delivery = db.deliveries.get(disc["delivery_id"])
    return _delivery_customer(delivery) if delivery else None


@bp.route("/stops/<sid>/deliveries", methods=["POST"])
def create_delivery(sid):
    data = body_json()
    category_id = field(data, "category_id", "s")
    pieces_promised = field(data, "pieces_promised", "i", minv=0)
    auth = authenticate()
    require_roles(auth, {"RouteDriver"})
    stop = path_get(db.stops, sid)
    cat = ref_get(db.categories, category_id)
    if stop["status"] != "PICKED_UP":
        raise ApiError(ERR_STOP_NOT_PICKED_UP, 409, "Stop must be PICKED_UP to manifest deliveries")
    pending = any(
        c["stop_id"] == stop["id"] and c["status"] not in ("RECEIVED", "SORTED", "VOIDED")
        for c in db.carts.values()
    )
    if pending:
        raise ApiError(ERR_CARTS_PENDING, 409, "All carts must be RECEIVED, SORTED, or VOIDED")
    delivery = db.new_entity()
    delivery.update(
        {
            "stop_id": stop["id"],
            "category_id": cat["id"],
            "pieces_promised": pieces_promised,
            "pieces_delivered": None,
            "shortfall_pieces": None,
            "overage_pieces": None,
            "status": "MANIFESTED",
        }
    )
    db.deliveries[delivery["id"]] = delivery
    return success(delivery, 201)


@bp.route("/stops/<sid>/deliveries", methods=["GET"])
def list_stop_deliveries(sid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    stop = path_get(db.stops, sid)
    cc_owns(auth, stop["customer_id"])
    items = [d for d in db.sorted_all(db.deliveries) if d["stop_id"] == stop["id"]]
    return list_response(items)


@bp.route("/deliveries/<did>", methods=["GET"])
def get_delivery(did):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    delivery = path_get(db.deliveries, did)
    cc_owns(auth, _delivery_customer(delivery))
    return success(delivery)


@bp.route("/deliveries/<did>/mark-delivered", methods=["POST"])
def mark_delivered(did):
    data = body_json()
    pieces_delivered = field(data, "pieces_delivered", "i", minv=0)
    expected_version = field(data, "expected_customer_version", "i")
    auth = authenticate()
    require_roles(auth, {"RouteDriver"})
    delivery = path_get(db.deliveries, did)
    if delivery["status"] != "MANIFESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Delivery is not MANIFESTED")
    stop = db.stops.get(delivery["stop_id"])
    if not stop or stop["status"] != "PICKED_UP":
        raise ApiError(ERR_STOP_NOT_PICKED_UP, 409, "Parent stop must be PICKED_UP")
    cust = db.customers.get(stop["customer_id"])
    if cust and cust["account_balance_cents"] > cust["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402, "Customer is past credit limit")
    if cust and expected_version != cust["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Customer version has advanced")
    delivery["pieces_delivered"] = pieces_delivered
    delivery["shortfall_pieces"] = max(0, delivery["pieces_promised"] - pieces_delivered)
    delivery["overage_pieces"] = max(0, pieces_delivered - delivery["pieces_promised"])
    delivery["status"] = "DELIVERED"
    db.touch(delivery)
    par = next(
        (
            p
            for p in db.par_levels.values()
            if p["customer_id"] == stop["customer_id"] and p["category_id"] == delivery["category_id"]
        ),
        None,
    )
    if par is not None:
        par["current_on_site_pieces"] += pieces_delivered
        db.touch(par)
    services.garment_cascade(
        cust,
        "LOADED_OUT",
        "AT_CUSTOMER",
        category_id=delivery["category_id"],
        limit=pieces_delivered,
    )
    if cust:
        db.touch(cust)  # balance-relevant mutation: customer version +1
    services.maybe_advance_stop_after_delivery(stop)
    return success(delivery)


@bp.route("/deliveries/<did>/confirm", methods=["POST"])
def confirm_delivery(did):
    auth = authenticate()
    require_roles(auth, {"CustomerContact"})
    delivery = path_get(db.deliveries, did)
    cc_owns(auth, _delivery_customer(delivery))
    if delivery["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Delivery is not DELIVERED")
    delivery["status"] = "CONFIRMED"
    db.touch(delivery)
    stop = db.stops.get(delivery["stop_id"])
    if stop:
        services.maybe_close_stop(stop)
    return success(delivery)


@bp.route("/deliveries/<did>/disputes", methods=["POST"])
def file_dispute(did):
    data = body_json()
    claimed = field(data, "claimed_shortfall_pieces", "i", minv=1)
    auth = authenticate()
    require_roles(auth, {"CustomerContact"})
    delivery = path_get(db.deliveries, did)
    cc_owns(auth, _delivery_customer(delivery))
    if delivery["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Delivery is not DELIVERED")
    if (delivery["shortfall_pieces"] or 0) < 1:
        raise ApiError(ERR_NO_SHORTAGE, 422, "Delivery has no shortfall")
    disc = db.new_entity()
    disc.update(
        {
            "delivery_id": delivery["id"],
            "claimed_shortfall_pieces": claimed,
            "approved_shortfall_pieces": None,
            "credit_cents": None,
            "status": "FILED",
            "_invoice_id": None,
        }
    )
    db.discrepancies[disc["id"]] = disc
    delivery["status"] = "DISPUTED"
    db.touch(delivery)
    stop = db.stops.get(delivery["stop_id"])
    if stop and stop["status"] == "DELIVERED":
        stop["status"] = "DISPUTED"
        db.touch(stop)
    return success(disc, 201)


@bp.route("/deliveries/<did>/disputes", methods=["GET"])
def list_delivery_disputes(did):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    delivery = path_get(db.deliveries, did)
    cc_owns(auth, _delivery_customer(delivery))
    items = [x for x in db.sorted_all(db.discrepancies) if x["delivery_id"] == delivery["id"]]
    return list_response(items)


@bp.route("/discrepancies/<xid>", methods=["GET"])
def get_discrepancy(xid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    disc = path_get(db.discrepancies, xid)
    cc_owns(auth, _discrepancy_customer(disc))
    return success(disc)


@bp.route("/discrepancies/<xid>/start-review", methods=["POST"])
def start_review(xid):
    auth = authenticate()
    require_roles(auth, {"CustomerServiceRep"})
    disc = path_get(db.discrepancies, xid)
    if disc["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Discrepancy is not FILED")
    disc["status"] = "UNDER_REVIEW"
    db.touch(disc)
    return success(disc)


@bp.route("/discrepancies/<xid>/approve", methods=["POST"])
def approve_discrepancy(xid):
    data = body_json()
    approved = field(data, "approved_shortfall_pieces", "i", minv=0)
    auth = authenticate()
    require_roles(auth, {"CustomerServiceRep"})
    disc = path_get(db.discrepancies, xid)
    if disc["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Discrepancy is not UNDER_REVIEW")
    delivery = db.deliveries.get(disc["delivery_id"])
    ceiling = min(disc["claimed_shortfall_pieces"], (delivery["shortfall_pieces"] or 0) if delivery else 0)
    if approved < 1 or approved > ceiling:
        raise ApiError(
            ERR_INVALID_APPROVED_QUANTITY,
            422,
            "approved_shortfall_pieces out of [1, min(claimed, shortfall)]",
        )
    cat = db.categories.get(delivery["category_id"]) if delivery else None
    repl = D(cat["replacement_cost_cents"]) if cat else D(0)
    disc["approved_shortfall_pieces"] = approved
    disc["credit_cents"] = round0(D(approved) * repl * D(services.CREDIT_RATE_PCT) / D(100))
    disc["status"] = "APPROVED"
    db.touch(disc)
    return success(disc)


@bp.route("/discrepancies/<xid>/reject", methods=["POST"])
def reject_discrepancy(xid):
    auth = authenticate()
    require_roles(auth, {"CustomerServiceRep"})
    disc = path_get(db.discrepancies, xid)
    if disc["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Discrepancy is not UNDER_REVIEW")
    disc["status"] = "REJECTED"
    db.touch(disc)
    delivery = db.deliveries.get(disc["delivery_id"])
    if delivery:
        services.maybe_settle_delivery(delivery)
    return success(disc)


@bp.route("/discrepancies/<xid>/apply-credit", methods=["POST"])
def apply_credit(xid):
    data = body_json()
    invoice_id = field(data, "invoice_id", "s")
    auth = authenticate()
    require_roles(auth, {"BillingClerk"})
    disc = path_get(db.discrepancies, xid)
    inv = ref_get(db.invoices, invoice_id)
    if disc["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Discrepancy is not APPROVED")
    cust_id = _discrepancy_customer(disc)
    if inv["customer_id"] != cust_id:
        raise ApiError(ERR_INVOICE_CUSTOMER_MISMATCH, 409, "Invoice belongs to a different customer")
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVOICE_NOT_DRAFT, 409, "Credit target invoice must be DRAFT")
    credit = disc["credit_cents"] or 0
    inv["credits_cents"] += credit
    services.recompute_invoice_total(inv)
    db.touch(inv)
    cust = db.customers.get(cust_id)
    if cust:
        cust["account_balance_cents"] -= credit
        db.touch(cust)
    disc["status"] = "CREDITED"
    disc["_invoice_id"] = inv["id"]
    db.touch(disc)
    delivery = db.deliveries.get(disc["delivery_id"])
    if delivery:
        services.maybe_settle_delivery(delivery)
    return success(disc)
