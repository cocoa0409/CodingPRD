"""MonitoringHold endpoints (PRD 3.12)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_monitoring_hold
from response import object_response, array_response
from services.lookup import get_hold, get_device, get_contract, require_owner_subscriber
from util import (get_json_body, require_fields, parse_iso, parse_pagination,
                  paginate, sort_by_created)

bp = Blueprint("holds", __name__)

HOLD_GAP_DAYS = 7


@bp.route("/pers/monitoring-holds", methods=["POST"])
def create_hold():
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    body = get_json_body()
    require_fields(body, ["device_id", "starts_at", "ends_at"])
    device = get_device(body["device_id"])
    # ownership through owning contract (priority 4)
    contract = get_contract(device["contract_id"])
    require_owner_subscriber(role, uid, contract["subscriber_id"])

    starts = parse_iso(body["starts_at"])
    ends = parse_iso(body["ends_at"])
    if not (ends > starts):
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")

    # buffered overlap (priority 13): rejected unless
    #   new.starts_at >= existing.ends_at + 7d  OR  new.ends_at + 7d <= existing.starts_at
    buffer = timedelta(days=HOLD_GAP_DAYS)
    for h in store.monitoring_holds.values():
        if h["status"] != "SCHEDULED" or h["device_id"] != body["device_id"]:
            continue
        separated = (starts >= h["ends_at_dt"] + buffer) or (ends + buffer <= h["starts_at_dt"])
        if not separated:
            raise err("ERR_HOLD_OVERLAP", "Hold within 7-day buffer of an existing scheduled hold")

    r = new_record()
    r.update({
        "device_id": body["device_id"],
        "starts_at_dt": starts,
        "ends_at_dt": ends,
        "status": "SCHEDULED",
    })
    store.monitoring_holds[r["id"]] = r
    return object_response(serialize_monitoring_hold(r), 201)


@bp.route("/pers/monitoring-holds/<hid>", methods=["GET"])
def get_hold_route(hid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    r = get_hold(hid)
    return object_response(serialize_monitoring_hold(r), 200)


@bp.route("/pers/monitoring-holds", methods=["GET"])
def list_holds():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    limit, offset = parse_pagination()
    items = list(store.monitoring_holds.values())
    if "device_id" in request.args:
        items = [h for h in items if h["device_id"] == request.args.get("device_id")]
    if "status" in request.args:
        items = [h for h in items if h["status"] == request.args.get("status")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_monitoring_hold(h) for h in page], limit, offset, total)


@bp.route("/pers/devices/<did>/monitoring-holds", methods=["GET"])
def list_device_holds(did):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    get_device(did)
    items = sort_by_created([h for h in store.monitoring_holds.values() if h["device_id"] == did])
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_monitoring_hold(h) for h in page], limit, offset, total)


@bp.route("/pers/monitoring-holds/<hid>/cancel", methods=["POST"])
def cancel_hold(hid):
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    r = get_hold(hid)
    device = get_device(r["device_id"])
    contract = get_contract(device["contract_id"])
    require_owner_subscriber(role, uid, contract["subscriber_id"])
    if r["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Hold is not SCHEDULED")
    r["status"] = "CANCELLED"
    touch(r)
    return object_response(serialize_monitoring_hold(r), 200)
