from flask import Blueprint, request

from auth import parse_auth, require_role
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ERR_INVALID_STATE,
                    ERR_EVENT_BUFFER)
from routes.operating_days import get_day
from util import (get_body, check_unknown, req_int, new_record, serialize,
                  sort_key, touch)
from services import settlement

bp = Blueprint("events", __name__)


def get_event(eid):
    e = store.events.get(eid)
    if e is None:
        raise not_found("capacity performance event not found")
    return e


@bp.post("/market/operating-days/<operatingDayId>/performance-events")
def create_event(operatingDayId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"start_interval", "end_interval"})
    start_interval = req_int(body, "start_interval", minimum=1, maximum=24)
    end_interval = req_int(body, "end_interval", minimum=1, maximum=24)
    if end_interval < start_interval:
        raise invalid_request("end_interval must be >= start_interval")
    day = get_day(operatingDayId)
    # one full gap hour is mandatory against every sibling event on the day
    for ev in store.events.values():
        if ev["operating_day_id"] != day["id"]:
            continue
        if ev["status"] not in ("DECLARED", "ACTIVE", "COMPLETED"):
            continue
        ok_gap = (start_interval >= ev["end_interval"] + 2
                  or ev["start_interval"] >= end_interval + 2)
        if not ok_gap:
            raise conflict(ERR_EVENT_BUFFER,
                           "event violates the 1-hour buffer rule against a sibling event")
    rec = new_record()
    rec.update({
        "operating_day_id": day["id"],
        "start_interval": start_interval,
        "end_interval": end_interval,
        "penalties_collected_cents": 0,
        "bonuses_paid_cents": 0,
        "status": "DECLARED",
        "_charges": {},
    })
    store.events[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/events/<eventId>")
def get_one(eventId):
    parse_auth()
    return ok(serialize(get_event(eventId)))


@bp.get("/market/events")
def list_events():
    parse_auth()
    rows = sorted(store.events.values(), key=sort_key)
    day_id = request.args.get("operating_day_id")
    status = request.args.get("status")
    if day_id is not None:
        rows = [r for r in rows if r["operating_day_id"] == day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/events/<eventId>/activate")
def activate(eventId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    event = get_event(eventId)
    if event["status"] != "DECLARED":
        raise conflict(ERR_INVALID_STATE, "only a DECLARED event can be activated")
    event["status"] = "ACTIVE"
    touch(event)
    return ok(serialize(event))


@bp.post("/market/events/<eventId>/complete")
def complete(eventId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    event = get_event(eventId)
    if event["status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, "only an ACTIVE event can be completed")
    day = store.operating_days[event["operating_day_id"]]
    if day["status"] not in ("DA_OPEN", "DA_GATED", "RT_COMPLETE"):
        raise conflict(ERR_INVALID_STATE,
                       "events cannot complete once preliminary settlement has run")
    settlement.capacity_performance_charge(event, day)
    event["status"] = "COMPLETED"
    touch(event)
    return ok(serialize(event))
