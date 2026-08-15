"""CustomerNotice endpoints."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_invalid_state, err_not_found, err_conflict
from services.common import (
    body, require_string, require_enum, parse_datetime_field,
    parse_pagination, paginate, get_work_order, get_notice, sweep_notice_expiry,
)

bp = Blueprint("notices", __name__)

CHANNELS = {"DOOR_HANGER", "MAIL", "SMS", "EMAIL"}


def notice_view(n):
    return {
        "id": n["id"],
        "work_order_id": n["work_order_id"],
        "address": n["address"],
        "channel": n["channel"],
        "event_start": n["event_start"],
        "sent_at": n["sent_at"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


@bp.post("/sewer/work-orders/<id>/customer-notices")
def create_notice(id):
    actor = get_actor()
    require_roles(actor, ["CustomerServiceRep"])
    wo = get_work_order(id)
    payload = body()
    address = require_string(payload, "address")
    channel = require_enum(payload, "channel", CHANNELS)
    event_start = parse_datetime_field(payload, "event_start", required=True)
    plan = db.plans[wo["plan_id"]]
    # for lining work the address must match an active lateral on the segment
    if plan["method"] == "CIPP_LINING":
        match = any(
            l["segment_id"] == plan["segment_id"] and l["active"] and l["address"] == address
            for l in db.laterals.values()
        )
        if not match:
            raise err_conflict("ERR_ADDRESS_NOT_ON_SEGMENT", "address does not match an active lateral on the segment")
    ent = {
        "id": db.new_id(),
        "work_order_id": wo["id"],
        "address": address,
        "channel": channel,
        "event_start": _format_iso(event_start),
        "sent_at": None,
        "status": "QUEUED",
    }
    db.stamp_new(ent)
    db.notices[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(notice_view(ent), status=201)


@bp.get("/sewer/customer-notices/<id>")
def get_notice_route(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer", "CustomerServiceRep"])
    n = get_notice(id)
    return success_object(notice_view(n))


@bp.get("/sewer/work-orders/<id>/customer-notices")
def list_notices(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer", "CustomerServiceRep", "CrewLead"])
    wo = get_work_order(id)
    limit, offset = parse_pagination()
    items = [n for n in db.notices.values() if n["work_order_id"] == wo["id"]]
    st = request.args.get("status")
    if st:
        items = [n for n in items if n["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([notice_view(n) for n in page], limit, offset, total)


@bp.post("/sewer/customer-notices/<id>/send")
def send_notice(id):
    actor = get_actor()
    require_roles(actor, ["CustomerServiceRep"])
    n = get_notice(id)
    if n["status"] != "QUEUED":
        raise err_invalid_state("notice not QUEUED")
    wo = db.work_orders[n["work_order_id"]]
    plan = db.plans[wo["plan_id"]]
    segment = db.segments[plan["segment_id"]]
    district = db.districts[segment["district_id"]]
    now = db.now_dt()
    ev = _parse_iso(n["event_start"])
    lead = timedelta(hours=district["notice_lead_hours"])
    if now > ev - lead:
        raise err_conflict("ERR_NOTICE_LEAD_VIOLATION", "send is past event_start - notice_lead_hours")
    n["sent_at"] = db.now_iso()
    n["status"] = "SENT"
    db.touch(n)
    sweep_notice_expiry()
    return success_object(notice_view(n))


@bp.post("/sewer/customer-notices/<id>/acknowledge")
def ack_notice(id):
    actor = get_actor()
    require_roles(actor, ["CustomerServiceRep"])
    n = get_notice(id)
    if n["status"] != "SENT":
        raise err_invalid_state("notice not SENT")
    n["status"] = "ACKNOWLEDGED"
    db.touch(n)
    sweep_notice_expiry()
    return success_object(notice_view(n))
