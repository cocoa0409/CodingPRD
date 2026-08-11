"""DCP Shipment endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import err_invalid_request, err_invalid_state, err_not_found
from services.core import (
    serialize_dcp_shipment, get_dcp_shipment, get_booking, new_entity_common, touch,
)
from services.clock import get_logical_clock
from util import iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("dcp", __name__)


FORMATS = {"DCP_2K", "DCP_4K", "FILM_35MM"}


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments", methods=["POST"])
@require_roles("Booker")
def create_dcp_shipment(did, baid, _user_id, _role):
    b = get_booking(did, baid)
    body = get_json_body()
    require_fields(body, ["content_format", "tracking_number"])
    if body["content_format"] not in FORMATS:
        raise err_invalid_request("content_format must be DCP_2K|DCP_4K|FILM_35MM")
    if b["print_status"] != "DCP_QUEUED":
        raise err_invalid_state("print_status must be DCP_QUEUED")
    common = new_entity_common()
    now_iso = iso_from_dt(get_logical_clock())
    s = {
        **common,
        "booking_agreement_id": baid,
        "content_format": body["content_format"],
        "tracking_number": body["tracking_number"],
        "shipped_at": now_iso,
        "delivered_at": None,
        "status": "IN_TRANSIT",
    }
    db.dcp_shipments[s["id"]] = s
    b["print_status"] = "DCP_SHIPPED"
    touch(b)
    return success_object(serialize_dcp_shipment(s), 201)


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def read_dcp_shipment(did, baid, sid, _user_id, _role):
    return success_object(serialize_dcp_shipment(get_dcp_shipment(did, baid, sid)))


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_dcp_shipments(did, baid, _user_id, _role):
    get_booking(did, baid)
    items = [s for s in db.dcp_shipments.values() if s["booking_agreement_id"] == baid]
    filters = {}
    for k in ("status", "booking_agreement_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_dcp_shipment, filters)


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments/<sid>/mark_delivered", methods=["POST"])
@require_roles("Exhibitor")
def mark_delivered(did, baid, sid, _user_id, _role):
    b = get_booking(did, baid)
    s = get_dcp_shipment(did, baid, sid)
    if s["status"] != "IN_TRANSIT":
        raise err_invalid_state("Shipment must be IN_TRANSIT")
    if b["deal_status"] not in ("ACCEPTED", "IN_PLAY"):
        raise err_invalid_state("Agreement must be ACCEPTED or IN_PLAY")
    s["status"] = "DELIVERED"
    s["delivered_at"] = iso_from_dt(get_logical_clock())
    touch(s)
    b["print_status"] = "DCP_DELIVERED"
    touch(b)
    return success_object(serialize_dcp_shipment(s))


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments/<sid>/mark_returned", methods=["POST"])
@require_roles("Booker")
def mark_returned(did, baid, sid, _user_id, _role):
    b = get_booking(did, baid)
    s = get_dcp_shipment(did, baid, sid)
    if b["print_status"] != "PRINT_STRUCK":
        raise err_invalid_state("print_status must be PRINT_STRUCK")
    s["status"] = "RETURNED"
    touch(s)
    b["print_status"] = "PRINT_RETURNED"
    touch(b)
    return success_object(serialize_dcp_shipment(s))


@bp.route("/distributors/<did>/booking-agreements/<baid>/dcp-shipments/<sid>/mark_lost", methods=["POST"])
@require_roles("Booker")
def mark_lost(did, baid, sid, _user_id, _role):
    b = get_booking(did, baid)
    s = get_dcp_shipment(did, baid, sid)
    if s["status"] not in ("QUEUED", "IN_TRANSIT"):
        raise err_invalid_state("Shipment must be QUEUED or IN_TRANSIT")
    s["status"] = "LOST"
    touch(s)
    if b["deal_status"] == "ACCEPTED":
        b["print_status"] = "DCP_QUEUED"
        touch(b)
    return success_object(serialize_dcp_shipment(s))
