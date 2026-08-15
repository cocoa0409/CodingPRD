"""Photo evidence endpoints (PRD 3.5)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN
from middleware import allowed
from response import success_object, success_list
from serializers import ser_photo
from routes.orders import get_order_or_404, TERMINAL_STATES
from validation import body, req_str, req_enum, req_iso, sort_and_page

bp = Blueprint("photos", __name__)

PHOTO_KINDS = {
    "FRONT", "REAR", "STREET",
    "INTERIOR_LIVING", "INTERIOR_KITCHEN", "INTERIOR_BATH",
    "DEFECT", "OTHER",
}


@bp.post("/bpo/valuation-orders/<order_id>/photos")
@allowed("Broker")
def create_photo(user_id, role, order_id):
    order = get_order_or_404(order_id)
    b = body()
    if order["fulfillment_status"] in TERMINAL_STATES:
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']} (terminal)", 409)
    photo_kind = req_enum(b, "photo_kind", PHOTO_KINDS)
    file_url = req_str(b, "file_url")
    captured_at = req_iso(b, "captured_at")
    now = db.logical_now()
    if captured_at < order["created_at"]:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'captured_at' must be on or after the order's creation", 400)
    if captured_at > now:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'captured_at' must not be in the future", 400)
    # Priority 30: only the assigned broker uploads evidence
    if user_id != order["assigned_broker_id"]:
        raise ApiError(ERR_FORBIDDEN, "Only the assigned broker may upload photo evidence", 403)

    record = db.stamp_new_append_only({
        "id": db.new_id(),
        "order_id": order_id,
        "photo_kind": photo_kind,
        "file_url": file_url,
        "captured_at": captured_at,
        "uploaded_by_broker_id": user_id,
    })
    db.photos[record["id"]] = record
    return success_object(ser_photo(record), 201)


@bp.get("/bpo/valuation-orders/<order_id>/photos")
@allowed("Broker", "OperationsManager", "QCReviewer", "DispatchCoordinator", "PlatformAdmin")
def list_photos(user_id, role, order_id):
    get_order_or_404(order_id)
    records = [p for p in db.photos.values() if p["order_id"] == order_id]
    photo_kind = request.args.get("photo_kind")
    if photo_kind is not None:
        records = [r for r in records if r["photo_kind"] == photo_kind]
    items, limit, offset, total = sort_and_page(records, ser_photo)
    return success_list(items, limit, offset, total)
