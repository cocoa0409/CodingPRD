"""PrivateDiningEvent routes (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_AREA_NOT_PRIVATE,
    ERR_AREA_BOUGHT_OUT, ERR_STALE_AREA_VERSION,
)
from middleware import require_roles
from response import object_response, array_response
from services import calc
from services.lookup import get_or_404
from services.cascades import run_buyout_cascade
from timeutil import parse_iso
from validators import (
    get_body, require_str, require_int, require_number, opt_number, paginate,
)

bp = Blueprint("private_dining", __name__)


@bp.post("/private-dining-events")
def create_event():
    require_roles({"Manager"})
    body = get_body()
    restaurant_id = require_str(body, "restaurant_id")
    dining_area_id = require_str(body, "dining_area_id")
    customer_id = require_str(body, "customer_id")
    if db.restaurants.get(restaurant_id) is None:
        raise err(ERR_NOT_FOUND, "restaurant not found")
    if db.dining_areas.get(dining_area_id) is None:
        raise err(ERR_NOT_FOUND, "dining area not found")
    if db.customers.get(customer_id) is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    party_size = require_int(body, "party_size", minimum=1)
    event_start = parse_iso(require_str(body, "event_start"), "event_start")
    event_end = parse_iso(require_str(body, "event_end"), "event_end")
    food_minimum_cents = require_int(body, "food_minimum_cents", minimum=0)
    deposit_pct = opt_number(body, "deposit_pct", 0.25, minimum=0, maximum=1)
    service_charge_pct = opt_number(body, "service_charge_pct", 0.0, minimum=0, maximum=1)

    rec = db.base_fields()
    rec.update({
        "restaurant_id": restaurant_id,
        "dining_area_id": dining_area_id,
        "customer_id": customer_id,
        "expected_dining_area_version": None,
        "party_size": party_size,
        "event_start": event_start,
        "event_end": event_end,
        "food_minimum_cents": food_minimum_cents,
        "deposit_pct": deposit_pct,
        "service_charge_pct": service_charge_pct,
        "deposit_due_cents": 0,
        "status": "INQUIRY",
    })
    db.private_dining_events[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/private-dining-events/<eid>")
def read_event(eid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.private_dining_events, eid)
    return object_response(db.serialize(rec), 200)


@bp.get("/private-dining-events")
def list_events():
    require_roles({"Manager", "Host", "Customer"})
    a = request.args
    restaurant_id = a.get("restaurant_id")
    dining_area_id = a.get("dining_area_id")
    customer_id = a.get("customer_id")
    status = a.get("status")
    records = []
    for e in db.private_dining_events.values():
        if restaurant_id is not None and e["restaurant_id"] != restaurant_id:
            continue
        if dining_area_id is not None and e["dining_area_id"] != dining_area_id:
            continue
        if customer_id is not None and e["customer_id"] != customer_id:
            continue
        if status is not None and e["status"] != status:
            continue
        records.append(e)
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)


@bp.post("/private-dining-events/<eid>/propose")
def propose_event(eid):
    require_roles({"Manager"})
    rec = get_or_404(db.private_dining_events, eid)
    if rec["status"] != "INQUIRY":
        raise err(ERR_INVALID_STATE, "event is not INQUIRY")
    area = db.dining_areas[rec["dining_area_id"]]
    if area["kind"] != "PRIVATE":
        raise err(ERR_AREA_NOT_PRIVATE, "dining area is not PRIVATE")
    rec["deposit_due_cents"] = calc.private_dining_deposit(
        rec["food_minimum_cents"], rec["deposit_pct"], rec["service_charge_pct"])
    rec["status"] = "PROPOSED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/private-dining-events/<eid>/revise")
def revise_event(eid):
    require_roles({"Manager"})
    rec = get_or_404(db.private_dining_events, eid)
    if rec["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "event is not PROPOSED")
    rec["status"] = "INQUIRY"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/private-dining-events/<eid>/confirm")
def confirm_event(eid):
    require_roles({"Manager"})
    rec = get_or_404(db.private_dining_events, eid)
    if rec["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "event is not PROPOSED")
    body = get_body()
    expected_version = require_int(body, "expected_dining_area_version")
    area = db.dining_areas[rec["dining_area_id"]]
    # area must be AVAILABLE
    if area["status"] != "AVAILABLE":
        raise err(ERR_INVALID_STATE, "dining area is not AVAILABLE")
    # no other CONFIRMED buyout on the same area overlaps the closed window
    for other in db.private_dining_events.values():
        if other["id"] == rec["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if other["dining_area_id"] != rec["dining_area_id"]:
            continue
        # closed-interval overlap [start, end]
        if rec["event_start"] <= other["event_end"] and other["event_start"] <= rec["event_end"]:
            raise err(ERR_AREA_BOUGHT_OUT, "another confirmed buyout overlaps")
    # OCC
    if expected_version != area["version"]:
        raise err(ERR_STALE_AREA_VERSION, "expected_dining_area_version is stale")

    area["status"] = "BOUGHT_OUT"
    db.touch(area)
    rec["expected_dining_area_version"] = expected_version
    run_buyout_cascade(rec)
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/private-dining-events/<eid>/complete")
def complete_event(eid):
    require_roles({"Manager"})
    rec = get_or_404(db.private_dining_events, eid)
    if rec["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "event is not CONFIRMED")
    area = db.dining_areas[rec["dining_area_id"]]
    area["status"] = "AVAILABLE"
    db.touch(area)
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/private-dining-events/<eid>/cancel")
def cancel_event(eid):
    require_roles({"Manager"})
    rec = get_or_404(db.private_dining_events, eid)
    if rec["status"] not in ("INQUIRY", "PROPOSED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "event is not cancellable")
    if rec["status"] == "CONFIRMED":
        area = db.dining_areas[rec["dining_area_id"]]
        area["status"] = "AVAILABLE"
        db.touch(area)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)
