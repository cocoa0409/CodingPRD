"""QueueTicket endpoints (PRD §3.3) — drive-in queue, assign (OCC), requeue, cancel."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_int, parse_pagination,
                    paginate, stamp_create, new_id, touch)
from errors import (ApiError, ERR_INVALID_STATE, ERR_BAY_NOT_OPEN,
                    ERR_STALE_BAY_VERSION)
from response import success_object, success_array
from services import lookup, workorder
from services.serialize import queue_ticket_out

bp = Blueprint("queue_tickets", __name__)

READ_ROLES = ("ShopManager", "ServiceAdvisor", "Technician")


@bp.route("/queue-tickets", methods=["POST"])
def create_ticket():
    require_role("ServiceAdvisor")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    vehicle_id = require_str(body, "vehicle_id")
    requested_package_id = require_str(body, "requested_package_id")
    lookup.get_shop(shop_id)
    lookup.get_vehicle(vehicle_id)
    lookup.get_package(requested_package_id)
    tkt = {
        "id": new_id(),
        "shop_id": shop_id,
        "vehicle_id": vehicle_id,
        "requested_package_id": requested_package_id,
        "queue_seq": db.next_queue_seq(shop_id),
        "assigned_bay_id": None,
        "work_order_id": None,
        "status": "WAITING",
    }
    stamp_create(tkt)
    db.queue_tickets[tkt["id"]] = tkt
    return success_object(queue_ticket_out(tkt), 201)


@bp.route("/queue-tickets", methods=["GET"])
def list_tickets():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.queue_tickets.values())
    for field in ("shop_id", "status", "vehicle_id", "requested_package_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [t for t in rows if t.get(field) == val]
    # Queue is ordered by intake sequence ascending (PRD §2.3 exception, §3.3).
    rows = sorted(rows, key=lambda t: t["queue_seq"])
    page, total = paginate(rows, limit, offset)
    return success_array([queue_ticket_out(t) for t in page], limit, offset, total)


@bp.route("/queue-tickets/<tkt_id>", methods=["GET"])
def get_ticket(tkt_id):
    require_role(*READ_ROLES)
    tkt = lookup.get_queue_ticket(tkt_id)
    return success_object(queue_ticket_out(tkt), 200)


@bp.route("/queue-tickets/<tkt_id>/assign", methods=["POST"])
def assign_ticket(tkt_id):
    require_role("ServiceAdvisor")
    tkt = lookup.get_queue_ticket(tkt_id)
    body = get_json_or_400()
    bay_id = require_str(body, "bay_id")
    expected_bay_version = require_int(body, "expected_bay_version")
    bay = lookup.get_bay(bay_id)
    # state: ticket must be WAITING; bay must be OPEN and same shop.
    if tkt["status"] != "WAITING":
        raise ApiError(ERR_INVALID_STATE, 409, "ticket is not WAITING")
    if bay["status"] != "OPEN":
        raise ApiError(ERR_BAY_NOT_OPEN, 409, "target bay is not OPEN")
    if bay["shop_id"] != tkt["shop_id"]:
        raise ApiError(ERR_BAY_NOT_OPEN, 409, "bay belongs to a different shop")
    # OCC: echoed version must match the bay's current version.
    if expected_bay_version != bay["version"]:
        raise ApiError(ERR_STALE_BAY_VERSION, 412, "bay version is stale")

    vehicle = lookup.get_vehicle(tkt["vehicle_id"])
    package = lookup.get_package(tkt["requested_package_id"])
    new_wo = workorder.create_work_order(
        shop_id=tkt["shop_id"], vehicle=vehicle, bay=bay, package=package,
        odometer_in=vehicle["odometer"], queue_ticket_id=tkt["id"],
    )
    tkt["status"] = "ASSIGNED"
    tkt["assigned_bay_id"] = bay["id"]
    tkt["work_order_id"] = new_wo["id"]
    touch(tkt)
    return success_object(queue_ticket_out(tkt), 200)


@bp.route("/queue-tickets/<tkt_id>/requeue", methods=["POST"])
def requeue_ticket(tkt_id):
    require_role("ServiceAdvisor")
    tkt = lookup.get_queue_ticket(tkt_id)
    if tkt["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409, "ticket is not ASSIGNED")
    wo = db.work_orders.get(tkt.get("work_order_id"))
    if wo is None or wo["service_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "cannot requeue once service has started")
    # Cancel the draft order, which frees its bay.
    workorder.cancel(wo)
    tkt["status"] = "WAITING"
    tkt["assigned_bay_id"] = None
    tkt["work_order_id"] = None
    touch(tkt)
    return success_object(queue_ticket_out(tkt), 200)


@bp.route("/queue-tickets/<tkt_id>/cancel", methods=["POST"])
def cancel_ticket(tkt_id):
    require_role("ServiceAdvisor")
    tkt = lookup.get_queue_ticket(tkt_id)
    if tkt["status"] != "WAITING":
        raise ApiError(ERR_INVALID_STATE, 409, "only a WAITING ticket may be cancelled")
    tkt["status"] = "CANCELLED"
    touch(tkt)
    return success_object(queue_ticket_out(tkt), 200)
