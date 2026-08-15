"""FulfillmentOrder endpoints: season/announcement lists + vendor pipeline."""
import uuid

from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_CONSTRAINT_VIOLATION
from util import (
    body_json, opt_str, opt_int, bump, success_object, list_response, get_or_404,
)

bp = Blueprint("fulfillment", __name__)


@bp.get("/awards/seasons/<sid>/fulfillment-orders")
def list_season_fulfillment(sid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "FulfillmentVendor"])
    s = get_or_404(store.seasons, sid, "Season")
    records = [f for f in store.fulfillment_orders.values() if f["season_id"] == s["id"]]
    status = request.args.get("status")
    item_type = request.args.get("item_type")
    if status:
        records = [f for f in records if f["status"] == status]
    if item_type:
        records = [f for f in records if f["item_type"] == item_type]
    return list_response(records, services.serialize_fulfillment)


@bp.get("/awards/announcements/<aid>/fulfillment-orders")
def list_announcement_fulfillment(aid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "FulfillmentVendor"])
    a = get_or_404(store.announcements, aid, "WinnerAnnouncement")
    records = [f for f in store.fulfillment_orders.values()
               if f["announcement_id"] == a["id"]]
    return list_response(records, services.serialize_fulfillment)


@bp.post("/awards/fulfillment-orders/<fid>/queue")
def queue_order(fid):
    _, role = authenticate()
    authorize(role, ["FulfillmentVendor"])
    fo = get_or_404(store.fulfillment_orders, fid, "FulfillmentOrder")
    body = body_json()
    engraving_text = opt_str(body, "engraving_text")
    quantity = opt_int(body, "quantity", None)
    services.guard_transition("fulfillment", fo, {"DRAFT"})
    ann = store.announcements.get(fo["announcement_id"])
    if ann is None or ann["status"] != "ANNOUNCED":
        raise_err(ERR_INVALID_STATE,
                  "the linked announcement must be ANNOUNCED")
    season = store.seasons.get(fo["season_id"])
    if season is None or season["status"] not in ("CEREMONY_LIVE", "PUBLISHED"):
        raise_err(ERR_INVALID_STATE,
                  "queueing requires season CEREMONY_LIVE or PUBLISHED")
    if quantity is not None and quantity < 1:
        raise_err(ERR_CONSTRAINT_VIOLATION, "quantity must be >= 1")
    if engraving_text is not None:
        fo["engraving_text"] = engraving_text
    if quantity is not None:
        fo["quantity"] = quantity
    fo["status"] = "QUEUED"
    fo["vendor_reference"] = "VR-" + uuid.uuid4().hex[:12].upper()
    bump(fo)
    return success_object(services.serialize_fulfillment(fo), 200)


@bp.post("/awards/fulfillment-orders/<fid>/start-production")
def start_production(fid):
    _, role = authenticate()
    authorize(role, ["FulfillmentVendor"])
    fo = get_or_404(store.fulfillment_orders, fid, "FulfillmentOrder")
    services.guard_transition("fulfillment", fo, {"QUEUED"})
    fo["status"] = "IN_PRODUCTION"
    bump(fo)
    return success_object(services.serialize_fulfillment(fo), 200)


@bp.post("/awards/fulfillment-orders/<fid>/ship")
def ship_order(fid):
    _, role = authenticate()
    authorize(role, ["FulfillmentVendor"])
    fo = get_or_404(store.fulfillment_orders, fid, "FulfillmentOrder")
    services.guard_transition("fulfillment", fo, {"IN_PRODUCTION"})
    fo["status"] = "SHIPPED"
    bump(fo)
    return success_object(services.serialize_fulfillment(fo), 200)


@bp.post("/awards/fulfillment-orders/<fid>/deliver")
def deliver_order(fid):
    _, role = authenticate()
    authorize(role, ["FulfillmentVendor"])
    fo = get_or_404(store.fulfillment_orders, fid, "FulfillmentOrder")
    services.guard_transition("fulfillment", fo, {"SHIPPED"})
    fo["status"] = "DELIVERED"
    bump(fo)
    return success_object(services.serialize_fulfillment(fo), 200)
