"""Session delivery routes & revision loop (PRD §3.9)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, get_pagination, paginate, get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list

bp = Blueprint("delivery", __name__)


def _delivery_of(booking_id):
    for d in db.session_deliveries.values():
        if d["booking_id"] == booking_id:
            return d
    return None


def _engineer_assigned(booking_id, engineer_id):
    return any(
        a["booking_id"] == booking_id and a["engineer_id"] == engineer_id
        for a in db.engineer_assignments.values()
    )


@bp.route("/studio/bookings/<bid>/delivery/deliver", methods=["POST"])
def deliver(bid):
    principal = get_principal()
    require_roles(principal, {"Engineer"})
    booking = get_or_404(db.bookings, bid, "booking")

    # Engineer ownership: must carry one of their own assignments on this booking.
    if not _engineer_assigned(bid, principal.user_id):
        raise err("ERR_FORBIDDEN", "engineer is not assigned to this booking")

    body = get_json_body()
    file_manifest = body.get("file_manifest")
    if file_manifest is None or not isinstance(file_manifest, list):
        raise err("ERR_INVALID_REQUEST", "file_manifest must be a list")

    delivery = _delivery_of(bid)

    if delivery is None:
        # First delivery (DRAFT -> DELIVERED). Requires COMPLETED + SETTLED and
        # non-empty manifest.
        if booking["schedule_status"] != "COMPLETED" or booking["settlement_status"] != "SETTLED":
            raise err("ERR_SESSION_NOT_DELIVERABLE", "booking is not COMPLETED and SETTLED")
        if len(file_manifest) == 0:
            raise err("ERR_SESSION_NOT_DELIVERABLE", "file_manifest must be non-empty")
        delivery = {
            "booking_id": bid,
            "file_manifest": list(file_manifest),
            "revision_round": 0,
            "status": "DELIVERED",
        }
        stamp_common(delivery)
        db.session_deliveries[delivery["id"]] = delivery
        return success_object(public(delivery), status=200)

    # Re-delivery: only from REVISION_REQUESTED.
    if delivery["status"] == "ACCEPTED":
        raise err("ERR_SESSION_NOT_DELIVERABLE", "delivery already accepted")
    if delivery["status"] != "REVISION_REQUESTED":
        raise err("ERR_INVALID_STATE", "delivery is not awaiting a revision")
    if len(file_manifest) == 0:
        raise err("ERR_SESSION_NOT_DELIVERABLE", "file_manifest must be non-empty")

    delivery["file_manifest"] = list(file_manifest)
    delivery["revision_round"] += 1
    delivery["status"] = "DELIVERED"
    touch(delivery)
    return success_object(public(delivery))


@bp.route("/studio/bookings/<bid>/delivery/request-revision", methods=["POST"])
def request_revision(bid):
    principal = get_principal()
    require_roles(principal, {"Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only act on their own bookings")

    delivery = _delivery_of(bid)
    if delivery is None:
        raise err("ERR_NOT_FOUND", "no delivery for this booking")
    if delivery["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "revision can only be requested from DELIVERED")

    delivery["status"] = "REVISION_REQUESTED"
    touch(delivery)
    return success_object(public(delivery))


@bp.route("/studio/bookings/<bid>/delivery/accept", methods=["POST"])
def accept(bid):
    principal = get_principal()
    require_roles(principal, {"Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only act on their own bookings")

    delivery = _delivery_of(bid)
    if delivery is None:
        raise err("ERR_NOT_FOUND", "no delivery for this booking")
    if delivery["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "delivery can only be accepted from DELIVERED")

    delivery["status"] = "ACCEPTED"
    touch(delivery)
    return success_object(public(delivery))


@bp.route("/studio/bookings/<bid>/delivery", methods=["GET"])
def list_delivery(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client" and booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only access their own bookings")
    if principal.role == "Engineer" and not _engineer_assigned(bid, principal.user_id):
        raise err("ERR_FORBIDDEN", "engineer is not assigned to this booking")
    deliveries = [d for d in db.session_deliveries.values() if d["booking_id"] == bid]
    limit, offset = get_pagination()
    page, total = paginate(deliveries, limit, offset)
    return success_array(public_list(page), limit, offset, total)
