"""Ops endpoints: MaintenanceWindow and CharterSupplement."""

from flask import Blueprint, request

from httpkit import (
    authenticate, err, err_invalid_state, err_validation, get_body,
    ignore_body, paginate, require_roles, respond_object, sorted_items,
)
from serializers import charter_supplement_json, maintenance_window_json, trip_json
from services import (
    MAINTENANCE_KINDS, AIRCRAFT_TYPES, get_aircraft, get_charter,
    get_maintenance_window, get_trip, new_common, touch,
    windows_of_aircraft,
)
from store import db

bp = Blueprint("ops", __name__)

MGR = "FlightDeptManager"
DISP = "Dispatcher"
MAINT = "MaintenancePlanner"
FIN = "FinanceAdmin"


# ---------------------------------------------------------------------------
# MaintenanceWindow (child of Aircraft)
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/aircraft/<aircraft_id>/maintenance-windows")
def create_maintenance_window(aircraft_id):
    authenticate()
    require_roles(MAINT)
    a = get_aircraft(aircraft_id)
    data = get_body([
        {"name": "window_start_utc", "type": "datetime", "required": True},
        {"name": "window_end_utc", "type": "datetime", "required": True},
        {"name": "maintenance_kind", "type": "enum",
         "values": MAINTENANCE_KINDS, "required": True},
    ])
    if not data["window_end_utc"] > data["window_start_utc"]:
        raise err_validation("window_end_utc must be strictly after window_start_utc")
    w = new_common()
    w.update({
        "aircraft_id": a["id"],
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "maintenance_kind": data["maintenance_kind"],
        # Auto-start fires on clock advance, not at creation.
        "status": "PLANNED",
    })
    db.maintenance_windows[w["id"]] = w
    # Parent posture is derived on read; the recomputation is implicit.
    return respond_object(maintenance_window_json(w), 201)


@bp.get("/flight-ops/aircraft/<aircraft_id>/maintenance-windows")
def list_maintenance_windows(aircraft_id):
    authenticate()
    require_roles(MGR, DISP, MAINT)
    a = get_aircraft(aircraft_id)
    items = sorted_items(windows_of_aircraft(a["id"]))
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [w for w in items if w["status"] == flt_status]
    return paginate([maintenance_window_json(w) for w in items])


@bp.post("/flight-ops/maintenance-windows/<window_id>/cancel")
def cancel_maintenance_window(window_id):
    authenticate()
    require_roles(MAINT)
    ignore_body()
    w = get_maintenance_window(window_id)
    if w["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED maintenance window can be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    return respond_object(maintenance_window_json(w))


@bp.post("/flight-ops/maintenance-windows/<window_id>/complete")
def complete_maintenance_window(window_id):
    authenticate()
    require_roles(MAINT)
    ignore_body()
    w = get_maintenance_window(window_id)
    if w["status"] != "IN_PROGRESS":
        raise err_invalid_state(
            "Only an IN_PROGRESS maintenance window can be completed")
    if not db.now() >= w["window_end_utc"]:
        raise err_invalid_state(
            "The logical clock has not reached the window end")
    w["status"] = "COMPLETED"
    touch(w)
    return respond_object(maintenance_window_json(w))


# ---------------------------------------------------------------------------
# CharterSupplement
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/charter-supplements")
def create_charter():
    authenticate()
    require_roles(DISP)
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "vendor_name", "type": "string", "required": True},
        {"name": "quoted_cost_cents", "type": "integer", "required": True},
        {"name": "aircraft_type_offered", "type": "enum",
         "values": AIRCRAFT_TYPES, "required": True},
    ])
    get_trip(data["trip_request_id"], fk=True)
    if data["quoted_cost_cents"] < 0:
        raise err_validation("quoted_cost_cents must be >= 0")
    c = new_common()
    c.update({
        "trip_request_id": data["trip_request_id"],
        "vendor_name": data["vendor_name"],
        "quoted_cost_cents": data["quoted_cost_cents"],
        "aircraft_type_offered": data["aircraft_type_offered"],
        "status": "QUOTED",
    })
    db.charter_supplements[c["id"]] = c
    return respond_object(charter_supplement_json(c), 201)


@bp.get("/flight-ops/charter-supplements")
def list_charters():
    authenticate()
    require_roles(MGR, DISP, FIN)
    items = sorted_items(db.charter_supplements.values())
    flt_trip = request.args.get("trip_request_id")
    if flt_trip is not None:
        items = [c for c in items if c["trip_request_id"] == flt_trip]
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [c for c in items if c["status"] == flt_status]
    return paginate([charter_supplement_json(c) for c in items])


@bp.get("/flight-ops/charter-supplements/<charter_id>")
def read_charter(charter_id):
    authenticate()
    require_roles(MGR, DISP, FIN)
    return respond_object(charter_supplement_json(get_charter(charter_id)))


@bp.post("/flight-ops/charter-supplements/<charter_id>/accept")
def accept_charter(charter_id):
    authenticate()
    require_roles(MGR)
    ignore_body()
    c = get_charter(charter_id)
    if c["status"] != "QUOTED":
        raise err_invalid_state("Only a QUOTED charter supplement can be accepted")
    t = db.trips.get(c["trip_request_id"])
    if t is None or not (t["approval_status"] == "APPROVED"
                         and t["assignment_status"] == "UNASSIGNED"):
        raise err("ERR_CHARTER_STATE_INVALID", 422,
                  "Charter can only be accepted while the trip is APPROVED and UNASSIGNED")
    c["status"] = "ACCEPTED"
    touch(c)
    # The charter vendor operates the trip: assignment jumps to DISPATCHED,
    # cost recognition deferred to settlement.
    t["assignment_status"] = "DISPATCHED"
    touch(t)
    return respond_object(charter_supplement_json(c))


@bp.post("/flight-ops/charter-supplements/<charter_id>/decline")
def decline_charter(charter_id):
    authenticate()
    require_roles(MGR)
    ignore_body()
    c = get_charter(charter_id)
    if c["status"] != "QUOTED":
        raise err_invalid_state("Only a QUOTED charter supplement can be declined")
    c["status"] = "DECLINED"
    touch(c)
    return respond_object(charter_supplement_json(c))
