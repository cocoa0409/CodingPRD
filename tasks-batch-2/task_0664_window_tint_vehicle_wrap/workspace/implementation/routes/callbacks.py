"""After-sales callbacks and free rework."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from models import stamp_create, serialize, touch
from response import success, success_list
from services import common

bp = Blueprint("callbacks", __name__)

CALLBACK_REASONS = {"BUBBLING", "PEELING", "COLOR_MISMATCH", "MEASUREMENT_ERROR"}
CALLBACK_OUTCOMES = {"REDO", "DENIED"}


def _customer_owns_work_order(role, user_id, work_order):
    if role == "Customer":
        quote = db.quotes.get(work_order["quote_id"])
        vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
        common.check_customer_owns_vehicle(role, user_id, vehicle)


@bp.route("/callbacks", methods=["POST"])
def open_callback():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    body = get_json_body()
    work_order_id = common.require_string(body, "work_order_id")
    reason = common.require_enum(body, "reason", CALLBACK_REASONS)

    wo = common.get_or_404(db.work_orders, work_order_id)
    _customer_owns_work_order(role, user_id, wo)

    # Eligibility: order COMPLETED and clock <= warranty_expires_at.
    if wo["install_status"] != "COMPLETED":
        raise ApiError(errors.ERR_OUT_OF_WARRANTY, 409, "WorkOrder is not COMPLETED.")
    warranty = db.parse_iso(wo["warranty_expires_at"])
    if warranty is None or db.now() > warranty:
        raise ApiError(errors.ERR_OUT_OF_WARRANTY, 409, "Current clock is past warranty_expires_at.")

    rec = {
        "work_order_id": work_order_id,
        "reason": reason,
        "outcome": None,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.callback_tickets[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/callbacks/<rid>", methods=["GET"])
def get_callback(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Customer"})
    rec = common.get_or_404(db.callback_tickets, rid)
    if role == "Customer":
        wo = db.work_orders.get(rec["work_order_id"])
        _customer_owns_work_order(role, user_id, wo)
    return success(serialize(rec), 200)


@bp.route("/callbacks", methods=["GET"])
def list_callbacks():
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.callback_tickets.values())
    wo_filter = request.args.get("work_order_id")
    if wo_filter is not None:
        items = [c for c in items if c["work_order_id"] == wo_filter]
    if role == "Customer":
        owned_wo = set()
        for w in db.work_orders.values():
            quote = db.quotes.get(w["quote_id"])
            vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
            if vehicle and vehicle["customer_user_id"] == user_id:
                owned_wo.add(w["id"])
        items = [c for c in items if c["work_order_id"] in owned_wo]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total, 200)


@bp.route("/callbacks/<rid>/resolve", methods=["POST"])
def resolve(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    rec = common.get_or_404(db.callback_tickets, rid)
    body = get_json_body()
    outcome = common.require_enum(body, "outcome", CALLBACK_OUTCOMES)

    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "CallbackTicket is not OPEN.")

    wo = db.work_orders.get(rec["work_order_id"])
    if outcome == "REDO":
        # REDO requires the referenced order be COMPLETED.
        if wo is None or wo["install_status"] != "COMPLETED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder is not COMPLETED for a REDO.")

    rec["outcome"] = outcome
    rec["status"] = "RESOLVED"

    if outcome == "REDO":
        # Re-reserve the same bay capacity for the redo (total_due not re-charged).
        bay = db.bays.get(wo["bay_id"])
        if bay is not None:
            bay["reserved_minutes"] += (wo["duration_minutes"] + wo["cure_buffer_minutes"])
            touch(bay)

    touch(rec)
    return success(serialize(rec), 200)


@bp.route("/callbacks/<rid>/close", methods=["POST"])
def close(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    rec = common.get_or_404(db.callback_tickets, rid)
    if rec["status"] != "RESOLVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "CallbackTicket is not RESOLVED.")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize(rec), 200)
