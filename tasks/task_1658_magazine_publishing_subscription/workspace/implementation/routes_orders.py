"""Routes: BackIssueOrders."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from db import store, new_record, touch
from errors import err
from routes_pub import list_response, PD_CM_FM
from serializers import ser_back_issue_order
from services import (
    BACK_ISSUE_MARKUP_BPS,
    SHIPPING_DOMESTIC_CENTS,
    SHIPPING_FOREIGN_CENTS,
    get_publication,
    get_subscriber,
    get_order,
    newsstand_available,
)
from util import body, success, req_int, require_fields, round_half_up_cents, months_between

bp = Blueprint("orders", __name__)

CM = ["CirculationManager"]
FM = ["FulfillmentManager"]
ORDER_CREATORS = ["CirculationManager", "FulfillmentManager"]


@bp.post("/publications/<publicationId>/subscribers/<subscriberId>/back-issue-orders")
@require_roles(ORDER_CREATORS)
def create_order(publicationId, subscriberId):
    pub = get_publication(publicationId)
    subscriber = get_subscriber(subscriberId)
    data = body()
    issue_id = data.get("issue_id")
    issue = store.issues.get(issue_id) if isinstance(issue_id, str) else None
    if issue is None or issue["publication_id"] != pub["id"]:
        raise err(
            "ERR_ISSUE_NOT_FOUND", "Issue id does not exist on this Publication"
        )
    quantity = data.get("quantity")
    if (
        isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity > 0
        and quantity > newsstand_available(issue)
    ):
        raise err("ERR_INSUFFICIENT_INVENTORY", "Not enough newsstand inventory")
    require_fields(data, ["issue_id", "quantity"])
    quantity = req_int(data, "quantity", minimum=1)
    # Unit price: base cover price, 1.5x markup when the cover date lies more
    # than 12 months in the past (round half up).
    age_months = months_between(issue["cover_date"], store.now())
    if age_months > 12:
        unit_price = round_half_up_cents(
            Decimal(pub["base_cover_price_cents"]) * BACK_ISSUE_MARKUP_BPS / 10000
        )
    else:
        unit_price = pub["base_cover_price_cents"]
    shipping = (
        SHIPPING_DOMESTIC_CENTS
        if subscriber["country_code"] == "US"
        else SHIPPING_FOREIGN_CENTS
    )
    rec = new_record()
    rec.update(
        {
            "subscriber_id": subscriber["id"],
            "issue_id": issue["id"],
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "shipping_cents": shipping,
            "total_charged_cents": quantity * unit_price + shipping,
            "is_recognized_revenue": False,
            "status": "PENDING",
            "_publication_id": pub["id"],
        }
    )
    store.back_issue_orders[rec["id"]] = rec
    return success(ser_back_issue_order(rec), 201)


@bp.get("/publications/<publicationId>/back-issue-orders")
@require_roles(PD_CM_FM)
def list_orders(publicationId):
    pub = get_publication(publicationId)
    records = [
        o
        for o in store.back_issue_orders.values()
        if o["_publication_id"] == pub["id"]
    ]
    return list_response(
        records, ser_back_issue_order, ("status", "subscriber_id", "issue_id")
    )


@bp.get("/publications/<publicationId>/back-issue-orders/<orderId>")
@require_roles(PD_CM_FM)
def get_order_detail(publicationId, orderId):
    get_publication(publicationId)
    return success(ser_back_issue_order(get_order(orderId, publicationId)), 200)


@bp.get("/back-issue-orders/<orderId>")
@require_roles(PD_CM_FM)
def get_order_flat(orderId):
    return success(ser_back_issue_order(get_order(orderId)), 200)


@bp.post("/publications/<publicationId>/back-issue-orders/<orderId>/fulfill")
@require_roles(FM)
def fulfill_order(publicationId, orderId):
    get_publication(publicationId)
    order = get_order(orderId, publicationId)
    if order["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "BackIssueOrder must be PENDING to fulfill")
    issue = store.issues.get(order["issue_id"])
    if issue is None or issue["status"] != "FINALIZED":
        raise err(
            "ERR_ISSUE_NOT_FINALIZED",
            "Back-issue fulfill requires Issue.status == FINALIZED",
        )
    if order["quantity"] > newsstand_available(issue):
        raise err("ERR_INSUFFICIENT_INVENTORY", "Not enough newsstand inventory")
    order["status"] = "FULFILLED"
    touch(order)
    return success(ser_back_issue_order(order), 200)


@bp.post("/publications/<publicationId>/back-issue-orders/<orderId>/ship")
@require_roles(FM)
def ship_order(publicationId, orderId):
    get_publication(publicationId)
    order = get_order(orderId, publicationId)
    if order["status"] != "FULFILLED":
        raise err("ERR_INVALID_STATE", "BackIssueOrder must be FULFILLED to ship")
    order["status"] = "SHIPPED"
    touch(order)
    return success(ser_back_issue_order(order), 200)


@bp.post("/publications/<publicationId>/back-issue-orders/<orderId>/deliver")
@require_roles(FM)
def deliver_order(publicationId, orderId):
    get_publication(publicationId)
    order = get_order(orderId, publicationId)
    if order["status"] != "SHIPPED":
        raise err("ERR_INVALID_STATE", "BackIssueOrder must be SHIPPED to deliver")
    order["status"] = "DELIVERED"
    # Back-issue revenue is recognized immediately, never deferred.
    order["is_recognized_revenue"] = True
    touch(order)
    return success(ser_back_issue_order(order), 200)


@bp.post("/publications/<publicationId>/back-issue-orders/<orderId>/cancel")
@require_roles(CM)
def cancel_order(publicationId, orderId):
    get_publication(publicationId)
    order = get_order(orderId, publicationId)
    if order["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "BackIssueOrder must be PENDING to cancel")
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser_back_issue_order(order), 200)


@bp.post("/publications/<publicationId>/back-issue-orders/<orderId>/refund")
@require_roles(CM)
def refund_order(publicationId, orderId):
    get_publication(publicationId)
    order = get_order(orderId, publicationId)
    if order["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "BackIssueOrder must be DELIVERED to refund")
    # Full refund of total_charged_cents; copies return to newsstand stock
    # (the REFUNDED status drops them out of the sold set automatically).
    order["status"] = "REFUNDED"
    touch(order)
    return success(ser_back_issue_order(order), 200)
