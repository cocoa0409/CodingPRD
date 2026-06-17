"""Tour endpoints + Tour state machine (PRD §3.4)."""
from flask import Blueprint, request

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import resolve, resolve_fk, owns_tour
from services.recompute import recompute_property_available_sf
from services.tour_engine import (parse_dt, release_tour_hold,
                                  reconcile_requirement_touring,
                                  space_overlap_conflict, broker_overlap_conflict)
from validate import (parse_body, check_str_type, check_bool_type,
                      parse_pagination, paginate)

bp = Blueprint("tours", __name__)


@bp.post("/tours")
def create_tour():
    user_id, role = authenticate()
    require_role(role, ["TenantBroker"])
    body = parse_body()
    requirement_id = check_str_type(body, "requirement_id", required=True)
    tenant_broker_id = check_str_type(body, "tenant_broker_id", required=True)
    space_id = check_str_type(body, "space_id", required=True)
    window_start = check_str_type(body, "window_start", required=True)
    window_end = check_str_type(body, "window_end", required=True)
    req = resolve_fk(db.requirements, requirement_id)
    broker = resolve_fk(db.brokers, tenant_broker_id)
    sp = resolve_fk(db.spaces, space_id)
    if tenant_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker mismatch")
    # window ordering constraint
    ws = parse_dt(window_start)
    we = parse_dt(window_end)
    if ws is None or we is None:
        raise err("ERR_INVALID_REQUEST", "Invalid window datetime")
    if not (ws < we):
        raise err("ERR_INVALID_REQUEST", "window_start must be before window_end")
    # requirement must be active
    if req["status"] not in ("OPEN", "TOURING", "NEGOTIATING"):
        raise err("ERR_REQUIREMENT_NOT_ACTIVE", "Requirement not active")
    rec = new_full_record({
        "requirement_id": requirement_id,
        "tenant_broker_id": tenant_broker_id,
        "space_id": space_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
        "holds_space": False,
    })
    db.tours[rec["id"]] = rec
    return success(serialize("Tour", rec), status=201)


@bp.get("/tours/<tour_id>")
def get_tour(tour_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.tours, tour_id)
    return success(serialize("Tour", rec), status=200)


@bp.get("/tours")
def list_tours():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    requirement_id = request.args.get("requirement_id")
    space_id = request.args.get("space_id")
    tenant_broker_id = request.args.get("tenant_broker_id")
    status = request.args.get("status")
    items = list(db.tours.values())
    if requirement_id is not None:
        items = [t for t in items if t["requirement_id"] == requirement_id]
    if space_id is not None:
        items = [t for t in items if t["space_id"] == space_id]
    if tenant_broker_id is not None:
        items = [t for t in items if t["tenant_broker_id"] == tenant_broker_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Tour", page), limit, offset, total)


@bp.post("/tours/<tour_id>/confirm")
def confirm_tour(tour_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    tour = resolve(db.tours, tour_id)
    sp = db.spaces.get(tour["space_id"])
    # Ownership: ListingBroker controls the space via its parent property
    from services.access import owns_space
    if sp is not None:
        owns_space(user_id, sp)
    body = parse_body()
    hold = check_bool_type(body, "hold", required=False, default=False)
    # state check
    if tour["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Tour not in REQUESTED")
    # space availability
    if sp is None or sp["status"] not in ("AVAILABLE", "ON_HOLD"):
        raise err("ERR_SPACE_NOT_AVAILABLE", "Space not available for showing")
    cand_start = parse_dt(tour["window_start"])
    cand_end = parse_dt(tour["window_end"])
    # space overlap (buffered) — priority 12
    if space_overlap_conflict(tour["space_id"], cand_start, cand_end, tour_id):
        raise err("ERR_TOUR_WINDOW_CONFLICT", "Tour window conflicts on space")
    # broker overlap (no buffer) — priority 12.5
    if broker_overlap_conflict(tour["tenant_broker_id"], cand_start, cand_end, tour_id):
        raise err("ERR_BROKER_DOUBLE_BOOKED", "Tenant broker double-booked")
    tour["status"] = "CONFIRMED"
    touch(tour)
    if hold:
        tour["holds_space"] = True
        if sp["status"] == "AVAILABLE":
            sp["status"] = "ON_HOLD"
            sp["held_by_tour_id"] = tour["id"]
            touch(sp)
            recompute_property_available_sf(sp["property_id"])
        # bubble Requirement OPEN -> TOURING
        req = db.requirements.get(tour["requirement_id"])
        if req is not None and req["status"] == "OPEN":
            req["status"] = "TOURING"
            touch(req)
    else:
        # first CONFIRMED tour still bubbles Requirement OPEN -> TOURING (PRD §3.3)
        req = db.requirements.get(tour["requirement_id"])
        if req is not None and req["status"] == "OPEN":
            req["status"] = "TOURING"
            touch(req)
    return success(serialize("Tour", tour), status=200)


@bp.post("/tours/<tour_id>/complete")
def complete_tour(tour_id):
    user_id, role = authenticate()
    require_role(role, ["TenantBroker"])
    tour = resolve(db.tours, tour_id)
    owns_tour(user_id, tour)
    if tour["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Tour not in CONFIRMED")
    ws = parse_dt(tour["window_start"])
    if db.current_clock() < ws:
        raise err("ERR_TOUR_NOT_STARTED", "Tour window has not started")
    release_tour_hold(tour)
    tour["status"] = "COMPLETED"
    touch(tour)
    reconcile_requirement_touring(tour["requirement_id"])
    return success(serialize("Tour", tour), status=200)


@bp.post("/tours/<tour_id>/cancel")
def cancel_tour(tour_id):
    user_id, role = authenticate()
    require_role(role, ["TenantBroker"])
    tour = resolve(db.tours, tour_id)
    owns_tour(user_id, tour)
    if tour["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Tour cannot be cancelled from current state")
    was_confirmed = tour["status"] == "CONFIRMED"
    release_tour_hold(tour)
    tour["status"] = "CANCELLED"
    touch(tour)
    if was_confirmed:
        reconcile_requirement_touring(tour["requirement_id"])
    return success(serialize("Tour", tour), status=200)


@bp.post("/tours/<tour_id>/no-show")
def no_show_tour(tour_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    tour = resolve(db.tours, tour_id)
    sp = db.spaces.get(tour["space_id"])
    from services.access import owns_space
    if sp is not None:
        owns_space(user_id, sp)
    if tour["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Tour not in CONFIRMED")
    we = parse_dt(tour["window_end"])
    if db.current_clock() < we:
        raise err("ERR_TOUR_NOT_ENDED", "Tour window has not ended")
    release_tour_hold(tour)
    tour["status"] = "NO_SHOW"
    touch(tour)
    reconcile_requirement_touring(tour["requirement_id"])
    return success(serialize("Tour", tour), status=200)
