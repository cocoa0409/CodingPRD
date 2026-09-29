"""Tract lifecycle endpoints: tracts, production plans, crew allocation,
mobilize / activate / complete, and the shutdown-order suspension loop."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import derive
from core import (
    ACCESS_CLASSES,
    RESERVING_STATUSES,
    SEASON_MONTHS,
    SHUTDOWN_REASONS,
    body,
    clock,
    created,
    db,
    endpoint,
    fail,
    new_record,
    ok,
    ordered,
    paginated,
    req_date,
    req_enum,
    req_int,
    req_num,
    req_str,
    rhu,
    to_date,
    touch,
)

bp = Blueprint("tracts", __name__)

WET_THRESHOLD = 72
MOVE_BUFFER_DAYS = 2


def seasonal_gate_open(access_class):
    months = SEASON_MONTHS[access_class]
    if months is None:
        return True
    return clock.now.month in months


# ---------------------------------------------------------------------------
# Tract
# ---------------------------------------------------------------------------
@bp.route("/tracts", methods=["POST"])
@endpoint("OperationsManager")
def create_tract(caller):
    payload = body()
    name = req_str(payload, "name", 1, 120)
    legal_description = req_str(payload, "legal_description", 1, 200)
    gross_acres = req_num(payload, "gross_acres", minimum=0, exclusive_min=True)
    planned_volume_tons = req_num(payload, "planned_volume_tons", minimum=0, exclusive_min=True)
    access_class = req_enum(payload, "access_class", ACCESS_CLASSES)
    rec = new_record()
    rec.update(
        {
            "name": name,
            "legal_description": legal_description,
            "gross_acres": gross_acres,
            "planned_volume_tons": planned_volume_tons,
            "access_class": access_class,
            "status": "PLANNED",
            "suspension_count": 0,
        }
    )
    db.tracts[rec["id"]] = rec
    return created(derive.tract_json(rec))


@bp.route("/tracts/<id>", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "MillScaler", "SafetyOfficer", "SettlementAccountant")
def get_tract(caller, id):
    rec = db.tracts.get(id)
    if rec is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    return ok(derive.tract_json(rec))


# ---------------------------------------------------------------------------
# ProductionPlan
# ---------------------------------------------------------------------------
@bp.route("/tracts/<id>/production-plans", methods=["POST"])
@endpoint("OperationsManager")
def create_production_plan(caller, id):
    payload = body()
    target = req_num(payload, "target_tons_per_week", minimum=0, exclusive_min=True)
    horizon = req_int(payload, "plan_horizon_weeks", minimum=1, maximum=52)
    expected_version = req_int(payload, "expected_tract_version")
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    if expected_version != tract["version"]:
        fail("ERR_STALE_TRACT_VERSION", "expected_tract_version does not match the tract's version")
    for prior in derive.plans_of_tract(tract["id"]):
        if prior["status"] in ("DRAFT", "APPROVED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)
    rec = new_record()
    rec.update(
        {
            "tract_id": tract["id"],
            "target_tons_per_week": target,
            "plan_horizon_weeks": horizon,
            "planned_volume_tons": rhu(target * horizon, 2),
            "status": "DRAFT",
        }
    )
    db.production_plans[rec["id"]] = rec
    touch(tract)
    return created(derive.production_plan_json(rec))


@bp.route("/tracts/<id>/production-plans", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SettlementAccountant")
def list_production_plans(caller, id):
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    records = derive.plans_of_tract(id)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginated(records, derive.production_plan_json)


@bp.route("/production-plans/<id>/approve", methods=["POST"])
@endpoint("OperationsManager")
def approve_production_plan(caller, id):
    rec = db.production_plans.get(id)
    if rec is None:
        fail("ERR_PRODUCTION_PLAN_NOT_FOUND", "no production plan %s" % id)
    if rec["status"] != "DRAFT":
        fail("ERR_INVALID_PLAN_STATE", "only a DRAFT plan may be approved")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(derive.production_plan_json(rec))


# ---------------------------------------------------------------------------
# CrewAssignment
# ---------------------------------------------------------------------------
@bp.route("/tracts/<id>/crew-assignments", methods=["POST"])
@endpoint("OperationsManager")
def create_crew_assignment(caller, id):
    payload = body()
    crew_id = req_str(payload, "crew_id")
    move_in_miles = req_int(payload, "move_in_miles", minimum=0, maximum=600)
    window_start = req_date(payload, "window_start")
    window_end = req_date(payload, "window_end")
    if window_end <= window_start:
        fail("ERR_VALIDATION", "window_end must be strictly after window_start")
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    crew = db.crews.get(crew_id)
    if crew is None:
        fail("ERR_CREW_NOT_FOUND", "no crew %s" % crew_id)
    # Half-open occupation window widened by a two-day move buffer on the tail
    # of every existing non-RELEASED assignment of this crew (PRD 3.3).
    for existing in ordered(list(db.crew_assignments.values())):
        if existing["crew_id"] != crew_id or existing["status"] == "RELEASED":
            continue
        existing_start = to_date(existing["window_start"])
        existing_end = to_date(existing["window_end"])
        if window_start < existing_end + timedelta(days=MOVE_BUFFER_DAYS) and window_end > existing_start:
            fail("ERR_CREW_WINDOW_CONFLICT", "crew occupation windows conflict")
    trips, cost = calc.move_in_cost(
        crew["equipment_pieces"], crew["crew_type"], tract["access_class"], move_in_miles
    )
    rec = new_record()
    rec.update(
        {
            "tract_id": tract["id"],
            "crew_id": crew["id"],
            "move_in_miles": move_in_miles,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "lowboy_trips": trips,
            "move_in_cost_cents": cost,
            "status": "SCHEDULED",
        }
    )
    db.crew_assignments[rec["id"]] = rec
    touch(tract)
    return created(derive.crew_assignment_json(rec))


@bp.route("/crew-assignments/<id>", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SafetyOfficer")
def get_crew_assignment(caller, id):
    rec = db.crew_assignments.get(id)
    if rec is None:
        fail("ERR_CREW_ASSIGNMENT_NOT_FOUND", "no crew assignment %s" % id)
    return ok(derive.crew_assignment_json(rec))


@bp.route("/crew-assignments", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SafetyOfficer")
def list_crew_assignments(caller):
    records = ordered(list(db.crew_assignments.values()))
    for key in ("crew_id", "tract_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.crew_assignment_json)


# ---------------------------------------------------------------------------
# Tract lifecycle
# ---------------------------------------------------------------------------
@bp.route("/tracts/<id>/mobilize", methods=["POST"])
@endpoint("OperationsManager")
def mobilize_tract(caller, id):
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    if tract["status"] != "PLANNED":
        fail("ERR_INVALID_TRACT_STATE", "only a PLANNED tract may be mobilized")
    plans = derive.plans_of_tract(tract["id"])
    if not any(p["status"] == "APPROVED" for p in plans):
        fail("ERR_PLAN_NOT_APPROVED", "the tract has no APPROVED production plan")
    assignments = derive.assignments_of_tract(tract["id"])
    scheduled = [a for a in assignments if a["status"] == "SCHEDULED"]
    if not scheduled:
        fail("ERR_NO_ELIGIBLE_CREW", "the tract has no SCHEDULED crew assignment")
    tract["status"] = "MOBILIZING"
    touch(tract)
    for assignment in scheduled:
        assignment["status"] = "MOVED_IN"
        touch(assignment)
        derive.set_crew_status(assignment, "MOBILIZING")
    return ok(derive.tract_json(tract))


@bp.route("/tracts/<id>/activate", methods=["POST"])
@endpoint("OperationsManager")
def activate_tract(caller, id):
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    if tract["status"] != "MOBILIZING":
        fail("ERR_INVALID_TRACT_STATE", "only a MOBILIZING tract may be activated")
    assignments = derive.assignments_of_tract(tract["id"])
    moved_in = [a for a in assignments if a["status"] == "MOVED_IN"]
    if not moved_in:
        fail("ERR_NO_ELIGIBLE_CREW", "the tract has no MOVED_IN crew assignment")
    if not seasonal_gate_open(tract["access_class"]):
        fail("ERR_SEASONAL_ACCESS_CLOSED", "the tract's access class forbids this calendar month")
    tract["status"] = "ACTIVE"
    touch(tract)
    for assignment in moved_in:
        assignment["status"] = "WORKING"
        touch(assignment)
        derive.set_crew_status(assignment, "ON_TRACT")
    return ok(derive.tract_json(tract))


@bp.route("/tracts/<id>/complete", methods=["POST"])
@endpoint("OperationsManager")
def complete_tract(caller, id):
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    if tract["status"] != "ACTIVE":
        fail("ERR_INVALID_TRACT_STATE", "only an ACTIVE tract may be completed")
    for load in derive.loads_of_tract(tract["id"]):
        if load["dispatch_status"] in RESERVING_STATUSES:
            fail("ERR_LOADS_STILL_OPEN", "loads off this tract are still in flight")
    tract["status"] = "COMPLETED"
    touch(tract)
    for assignment in derive.assignments_of_tract(tract["id"]):
        if assignment["status"] in ("MOVED_IN", "WORKING", "STOOD_DOWN"):
            assignment["status"] = "RELEASED"
            touch(assignment)
            derive.set_crew_status(assignment, "IDLE")
    for plan in derive.plans_of_tract(tract["id"]):
        if plan["status"] == "APPROVED":
            plan["status"] = "SUPERSEDED"
            touch(plan)
    return ok(derive.tract_json(tract))


# ---------------------------------------------------------------------------
# ShutdownOrder
# ---------------------------------------------------------------------------
@bp.route("/tracts/<id>/shutdown-orders", methods=["POST"])
@endpoint("OperationsManager")
def create_shutdown_order(caller, id):
    payload = body()
    reason = req_enum(payload, "reason", SHUTDOWN_REASONS)
    moisture = req_int(payload, "soil_moisture_index", minimum=0, maximum=100)
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    # Ladder rung 7 -- deliberately above the tract-state rung.
    for order in db.shutdown_orders.values():
        if order["tract_id"] == tract["id"] and order["status"] == "ACTIVE":
            fail("ERR_ACTIVE_SHUTDOWN_ORDER", "the tract already carries an ACTIVE shutdown order")
    if tract["status"] != "ACTIVE":
        fail("ERR_INVALID_TRACT_STATE", "only an ACTIVE tract may be shut down")
    if reason == "WET_WEATHER" and moisture < WET_THRESHOLD:
        fail("ERR_WET_THRESHOLD_NOT_MET", "a WET_WEATHER shutdown requires soil_moisture_index >= 72")
    rec = new_record()
    rec.update(
        {
            "tract_id": tract["id"],
            "reason": reason,
            "soil_moisture_index": moisture,
            "lift_soil_moisture_index": None,
            "declared_at": clock.iso(),
            "lifted_at": None,
            "status": "ACTIVE",
        }
    )
    db.shutdown_orders[rec["id"]] = rec
    # Hop 1
    tract["status"] = "SUSPENDED"
    tract["suspension_count"] += 1
    touch(tract)
    # Hops 2a / 3a -- the ground
    for assignment in derive.assignments_of_tract(tract["id"]):
        if assignment["status"] == "WORKING":
            assignment["status"] = "STOOD_DOWN"
            touch(assignment)
            derive.set_crew_status(assignment, "STOOD_DOWN")
    # Hops 2b / 3b / 4b -- the wood.  Loads already AT_MILL are left alone.
    for load in ordered(derive.loads_of_tract(tract["id"])):
        if load["dispatch_status"] in ("DISPATCHED", "IN_TRANSIT"):
            derive.cancel_load(load)
    return created(derive.shutdown_order_json(rec))


@bp.route("/tracts/<id>/shutdown-orders", methods=["GET"])
@endpoint("PlatformAdmin", "OperationsManager", "SafetyOfficer")
def list_shutdown_orders(caller, id):
    tract = db.tracts.get(id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % id)
    records = ordered([o for o in db.shutdown_orders.values() if o["tract_id"] == id])
    for key in ("status", "reason"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.shutdown_order_json)


@bp.route("/shutdown-orders/<id>/lift", methods=["POST"])
@endpoint("OperationsManager")
def lift_shutdown_order(caller, id):
    payload = body()
    moisture = req_int(payload, "soil_moisture_index", minimum=0, maximum=100)
    order = db.shutdown_orders.get(id)
    if order is None:
        fail("ERR_SHUTDOWN_ORDER_NOT_FOUND", "no shutdown order %s" % id)
    if order["status"] != "ACTIVE":
        fail("ERR_INVALID_SHUTDOWN_ORDER_STATE", "the shutdown order is already LIFTED")
    if order["reason"] == "WET_WEATHER" and moisture >= WET_THRESHOLD:
        fail("ERR_WET_THRESHOLD_STILL_MET", "lifting a WET_WEATHER order requires soil_moisture_index < 72")
    order["status"] = "LIFTED"
    order["lifted_at"] = clock.iso()
    order["lift_soil_moisture_index"] = moisture
    touch(order)
    tract = db.tracts.get(order["tract_id"])
    if tract is not None and tract["status"] == "SUSPENDED":
        remaining = [
            o
            for o in db.shutdown_orders.values()
            if o["tract_id"] == tract["id"] and o["status"] == "ACTIVE"
        ]
        if not remaining:
            tract["status"] = "ACTIVE"
            touch(tract)
            for assignment in derive.assignments_of_tract(tract["id"]):
                if assignment["status"] == "STOOD_DOWN":
                    assignment["status"] = "WORKING"
                    touch(assignment)
                    derive.set_crew_status(assignment, "ON_TRACT")
    return ok(derive.shutdown_order_json(order))
