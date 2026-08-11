"""Movement endpoints: nominate, list, get, schedule, arrive, start, complete,
cancel (with waitlist promotion), resume."""
from datetime import timedelta

from flask import Blueprint, request

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import movement_view
from services import calc
from services.common import (touch, get_lease_or_404, get_tank_or_404,
                             get_resource_or_404, get_movement_or_404,
                             active_allocation_for)
from services import lifecycle
from validation import (get_body, req_string, req_enum, req_number, req_datetime,
                        sort_and_page, PRODUCT_GRADES, DIRECTIONS, MODES)

bp = Blueprint("movements", __name__)

MODE_TO_RESOURCE_TYPE = {"VESSEL": "DOCK", "RAIL": "RAIL_RACK", "TRUCK": "TRUCK_BAY"}


@bp.post("/movements")
def create_movement():
    require_roles("Scheduler")
    body = get_body()
    lease_id = req_string(body, "lease_id")
    tank_id = req_string(body, "tank_id")
    direction = req_enum(body, "direction", DIRECTIONS)
    mode = req_enum(body, "mode", MODES)
    product_grade = req_enum(body, "product_grade", PRODUCT_GRADES)
    declared_volume_bbl = req_number(body, "declared_volume_bbl", gt=0)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")

    # Existence (priority 5): body FKs resolve.
    lease = get_lease_or_404(lease_id)
    tank = get_tank_or_404(tank_id)

    # Lease / tank state gates.
    if lease["status"] != "ACTIVE":
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Movement creation requires the lease to be ACTIVE")
    if tank["status"] != "AVAILABLE":
        raise err("ERR_TANK_NOT_AVAILABLE",
                  "Movement creation requires the tank to be AVAILABLE")

    # Business constraints.
    if product_grade != lease["product_grade"] or product_grade != tank["product_grade"]:
        raise err("ERR_PRODUCT_MISMATCH",
                  "Movement product_grade must equal both the lease's and the tank's grade")
    if not window_end > window_start:
        raise err("ERR_WINDOW_INVALID", "window_end must be strictly after window_start")

    allocation = active_allocation_for(lease["id"], tank["id"])
    if allocation is None:
        raise err("ERR_NO_ACTIVE_ALLOCATION",
                  "No ACTIVE allocation covers this (lease, tank)")
    if calc.dec(declared_volume_bbl) > calc.dec(allocation["allocated_bbl"]):
        raise err("ERR_VOLUME_EXCEEDS_ALLOCATION",
                  "declared_volume_bbl exceeds the ACTIVE allocation's allocated_bbl")

    now = CLOCK.now()
    STORE.movement_sequence += 1
    movement = {
        "id": new_id(),
        "sequence_no": STORE.movement_sequence,
        "lease_id": lease["id"],
        "tank_id": tank["id"],
        "resource_id": None,
        "direction": direction,
        "mode": mode,
        "product_grade": product_grade,
        "declared_volume_bbl": declared_volume_bbl,
        "window_start": window_start,
        "window_end": window_end,
        "actual_arrival_at": None,
        "actual_start_at": None,
        "actual_complete_at": None,
        "demurrage_estimated_amount": None,
        "demurrage_actual_amount": None,
        "status": "NOMINATED",
        "billing_status": "UNBILLED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.movements[movement["id"]] = movement
    return success_object(movement_view(movement), status=201)


@bp.get("/movements")
def list_movements():
    current_user()
    rows = list(STORE.movements.values())
    for param, field in (("lease_id", "lease_id"), ("tank_id", "tank_id"),
                         ("resource_id", "resource_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [m for m in rows if m[field] == value]
    page, total, limit, offset = sort_and_page(
        rows, key=lambda m: (m["created_at"], m["sequence_no"]))
    return success_list([movement_view(m) for m in page], total, limit, offset)


@bp.get("/movements/<movementId>")
def get_movement(movementId):
    current_user()
    movement = get_movement_or_404(movementId)
    return success_object(movement_view(movement))


@bp.post("/movements/<movementId>/schedule")
def schedule_movement(movementId):
    require_roles("Scheduler")
    body = get_body()
    resource_id = req_string(body, "resource_id")
    movement = get_movement_or_404(movementId)
    if movement["status"] != "NOMINATED":
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; schedule requires NOMINATED"
                  % (movementId, movement["status"]))
    lease = get_lease_or_404(movement["lease_id"])
    tank = get_tank_or_404(movement["tank_id"])
    resource = get_resource_or_404(resource_id)

    if lease["status"] != "ACTIVE":
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Scheduling requires the lease to be ACTIVE")
    if tank["status"] != "AVAILABLE":
        raise err("ERR_TANK_NOT_AVAILABLE",
                  "Scheduling requires the tank to be AVAILABLE")
    if resource["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_UNAVAILABLE",
                  "Resource %s is OUT_OF_SERVICE" % resource_id)
    if resource["resource_type"] != MODE_TO_RESOURCE_TYPE[movement["mode"]]:
        raise err("ERR_RESOURCE_TYPE_MISMATCH",
                  "Resource type %s does not match movement mode %s"
                  % (resource["resource_type"], movement["mode"]))
    if calc.window_conflict(resource, movement["window_start"], movement["window_end"],
                            exclude_movement_id=movement["id"]):
        raise err("ERR_WINDOW_CONFLICT",
                  "Requested window collides with existing occupation on the resource")
    allocation = active_allocation_for(lease["id"], tank["id"])
    if allocation is None:
        raise err("ERR_NO_ACTIVE_ALLOCATION",
                  "No ACTIVE allocation covers this (lease, tank)")
    if calc.dec(movement["declared_volume_bbl"]) > calc.dec(allocation["allocated_bbl"]):
        raise err("ERR_VOLUME_EXCEEDS_ALLOCATION",
                  "declared_volume_bbl exceeds the ACTIVE allocation's allocated_bbl")

    lifecycle.promote_to_scheduled(movement, resource)
    return success_object(movement_view(movement))


@bp.post("/movements/<movementId>/arrive")
def arrive_movement(movementId):
    require_roles("Scheduler")
    movement = get_movement_or_404(movementId)
    if movement["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; arrive requires SCHEDULED"
                  % (movementId, movement["status"]))
    movement["status"] = "ARRIVED"
    movement["actual_arrival_at"] = CLOCK.now()
    touch(movement)
    return success_object(movement_view(movement))


def _check_vapor_gate(tank):
    """Shared start/resume vapor-permit gate (PRD 3.6)."""
    if tank["vapor_control_class"] != "VRU_REQUIRED":
        return
    state, _permit = calc.vapor_permit_state(tank)
    if state == "NONE":
        raise err("ERR_VAPOR_PERMIT_REQUIRED",
                  "Tank requires an APPROVED VAPOR_CONTROL permit")
    if state == "WINDOW":
        raise err("ERR_PERMIT_WINDOW_INSUFFICIENT",
                  "The approved permit's validity window does not cover the current time")


@bp.post("/movements/<movementId>/start")
def start_movement(movementId):
    require_roles("Scheduler")
    movement = get_movement_or_404(movementId)
    if movement["status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; start requires ARRIVED"
                  % (movementId, movement["status"]))
    opening, _closing = lifecycle.gauge_pair(movement["id"])
    if opening is None:
        raise err("ERR_GAUGE_MISSING",
                  "An OPENING gauge ticket must exist before start")
    tank = get_tank_or_404(movement["tank_id"])
    _check_vapor_gate(tank)
    now = CLOCK.now()
    if now > movement["window_end"] + timedelta(minutes=calc.LATE_GRACE_MINUTES):
        raise err("ERR_WINDOW_LAPSED",
                  "Start attempted after window_end + 30 minute grace")
    movement["status"] = "IN_PROGRESS"
    movement["actual_start_at"] = now
    touch(movement)
    return success_object(movement_view(movement))


@bp.post("/movements/<movementId>/complete")
def complete_movement(movementId):
    require_roles("Scheduler")
    movement = get_movement_or_404(movementId)
    if movement["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; complete requires IN_PROGRESS"
                  % (movementId, movement["status"]))
    opening, closing = lifecycle.gauge_pair(movement["id"])
    if closing is None:
        raise err("ERR_GAUGE_MISSING",
                  "A CLOSING gauge ticket must exist before complete")

    now = CLOCK.now()
    movement["status"] = "COMPLETED"
    movement["actual_complete_at"] = now
    movement["demurrage_actual_amount"] = calc.demurrage_actual_settlement(movement)
    touch(movement)

    # Auto-create the 1:1 PROVISIONAL custody transfer.
    ct_now = CLOCK.now()
    ct = {
        "id": new_id(),
        "movement_id": movement["id"],
        "provisional_volume_bbl": calc.provisional_volume(movement, opening, closing),
        "certified_volume_bbl": None,
        "shrinkage_bbl": None,
        "allowed_loss_bbl": None,
        "excess_loss_bbl": None,
        "excess_loss_charge": None,
        "certified_by_user_id": None,
        "status": "PROVISIONAL",
        "created_at": ct_now,
        "updated_at": ct_now,
        "version": 1,
    }
    STORE.custody_transfers[ct["id"]] = ct

    tank = get_tank_or_404(movement["tank_id"])
    calc.recompute_tank_inventory(tank)
    touch(tank)
    return success_object(movement_view(movement))


@bp.post("/movements/<movementId>/cancel")
def cancel_movement(movementId):
    require_roles("Scheduler")
    movement = get_movement_or_404(movementId)
    if movement["status"] not in ("NOMINATED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; cancel requires NOMINATED or SCHEDULED"
                  % (movementId, movement["status"]))
    was_scheduled = movement["status"] == "SCHEDULED"
    freed_resource = None
    if was_scheduled and movement.get("resource_id"):
        freed_resource = STORE.resources.get(movement["resource_id"])
    movement["status"] = "CANCELLED"
    touch(movement)
    if freed_resource is not None:
        calc.run_waitlist_promotion(freed_resource)
    return success_object(movement_view(movement))


@bp.post("/movements/<movementId>/resume")
def resume_movement(movementId):
    require_roles("Scheduler")
    movement = get_movement_or_404(movementId)
    if movement["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE",
                  "Movement %s is %s; resume requires SUSPENDED"
                  % (movementId, movement["status"]))
    tank = get_tank_or_404(movement["tank_id"])
    _check_vapor_gate(tank)
    movement["status"] = "IN_PROGRESS"
    touch(movement)
    return success_object(movement_view(movement))
