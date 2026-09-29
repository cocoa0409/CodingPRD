"""Service records: the mass ledger of the platform (PRD 3.3, 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import (COMPLIANCE_MANAGER, TECHNICIAN, endpoint,
                        read_endpoint, require_technician_identity)
from services import events, guards, ledger, posture

bp = Blueprint("service_records", __name__)

ZERO = Decimal("0")
ZERO_1 = Decimal("0.0")


@bp.post("/service-records")
@endpoint([TECHNICIAN])
def create_service_record():
    payload = validate.body()
    system_id = validate.req_id(payload, "system_id")
    technician_id = validate.req_id(payload, "technician_id")
    recovery_equipment_id = validate.req_id(payload, "recovery_equipment_id")
    cylinder_id = validate.opt_id(payload, "cylinder_id")
    leak_event_id = validate.opt_id(payload, "leak_event_id")
    service_type = validate.req_enum(payload, "service_type", constants.SERVICE_TYPES)
    performed_at = validate.req_instant(payload, "performed_at")
    duration_minutes = validate.req_int(payload, "duration_minutes",
                                        minimum=1, maximum=1440)
    expected_system_version = validate.req_int(payload, "expected_system_version")
    added = validate.opt_decimal(payload, "refrigerant_added_lbs",
                                 minimum=ZERO, default=ZERO_1)
    recovered = validate.opt_decimal(payload, "refrigerant_recovered_lbs",
                                     minimum=ZERO, default=ZERO_1)
    lost = validate.opt_decimal(payload, "refrigerant_lost_lbs",
                                minimum=ZERO, default=ZERO_1)
    # PRD 3.3: the cylinder becomes mandatory once mass actually moves.
    if cylinder_id is None and (added > ZERO or recovered > ZERO):
        raise invalid("cylinder_id is required when refrigerant mass moves")

    system = db.require("systems", system_id)
    technician = db.require("technicians", technician_id)
    equipment = db.require("recovery_equipment", recovery_equipment_id)
    cylinder = db.require("cylinders", cylinder_id) if cylinder_id else None
    leak_event = db.require("leak_events", leak_event_id) if leak_event_id else None

    require_technician_identity(technician_id)
    if expected_system_version != system["version"]:
        raise ApiError("ERR_STALE_SYSTEM_VERSION")
    guards.require_active_system(system)

    guards.require_not_suspended(technician)
    guards.require_certification_current(technician, performed_at)
    guards.require_certification_class(technician, system)

    handled_type_id = guards.handled_refrigerant_type_id(system, service_type)
    if service_type in constants.EQUIPMENT_GATED_SERVICE_TYPES:
        guards.require_equipment_certified(equipment, performed_at)
        handled_type = db.get("refrigerant_types", handled_type_id)
        if handled_type is not None:
            guards.require_equipment_pressure_class(equipment, handled_type)
        if cylinder is not None:
            guards.require_chemistry_match(cylinder, handled_type_id)
    if cylinder is not None and added > ZERO:
        guards.require_reclaimed_before_reuse(cylinder)

    guards.require_same_store(equipment, system["store_id"])
    if cylinder is not None:
        guards.require_same_store(cylinder, system["store_id"])

    guards.require_not_after_clock(performed_at)
    if performed_at < system["installed_on"]:
        raise ApiError("ERR_SERVICE_DATE_OUT_OF_RANGE")

    occupies_until = util.add_minutes(performed_at, duration_minutes)
    equipment_released_at = util.add_minutes(
        occupies_until, constants.EQUIPMENT_DECONTAMINATION_BUFFER_MINUTES)
    guards.require_no_technician_conflict(technician_id, performed_at, occupies_until)
    guards.require_no_equipment_conflict(recovery_equipment_id, performed_at,
                                         equipment_released_at)

    record = db.new_entity()
    record.update({
        "system_id": system_id,
        "technician_id": technician_id,
        "recovery_equipment_id": recovery_equipment_id,
        "cylinder_id": cylinder_id,
        "leak_event_id": leak_event_id,
        "service_type": service_type,
        "performed_at": performed_at,
        "duration_minutes": duration_minutes,
        "occupies_until": occupies_until,
        "equipment_released_at": equipment_released_at,
        "refrigerant_added_lbs": added,
        "refrigerant_recovered_lbs": recovered,
        "refrigerant_lost_lbs": lost,
        "system_charge_after_lbs": None,
        "leak_rate_pct_after": None,
        "retention_until": ledger.retention_from(performed_at),
        "voided": False,
        "voided_at": None,
        "void_reason_code": None,
    })
    guards.check_mass_movements(system, cylinder, added, recovered, lost, record)

    db.insert("service_records", record)

    if cylinder is not None:
        cylinder_snap = db.snapshot(cylinder)
        cylinder["current_contents_lbs"] = util.q1(
            cylinder["current_contents_lbs"] - added + recovered)
        if recovered > ZERO and cylinder["disposition"] == "VIRGIN":
            cylinder["disposition"] = "RECOVERED"
        db.commit(cylinder, cylinder_snap)

    if service_type == "RETROFIT_CONVERSION":
        approved = [
            plan for plan in db.values("retrofit_plans")
            if plan["system_id"] == system_id and plan["status"] == "APPROVED"
        ]
        if len(approved) == 1:
            plan = approved[0]
            plan_snap = db.snapshot(plan)
            plan["status"] = "IN_PROGRESS"
            db.commit(plan, plan_snap)

    # PRD 2.9 pinned cascade.
    ledger.recompute_charge(system)
    ledger.recompute_leak_rate(system)
    record["system_charge_after_lbs"] = system["current_charge_lbs"]
    record["leak_rate_pct_after"] = system["leak_rate_pct"]
    events.maybe_auto_open(system, record)
    posture.system_cascade(system)
    return response.created(record)


@bp.get("/service-records")
@read_endpoint
def list_service_records():
    filters = {
        "system_id": request.args.get("system_id"),
        "technician_id": request.args.get("technician_id"),
        "recovery_equipment_id": request.args.get("recovery_equipment_id"),
        "cylinder_id": request.args.get("cylinder_id"),
        "leak_event_id": request.args.get("leak_event_id"),
        "service_type": request.args.get("service_type"),
        "voided": response.bool_filter("voided"),
    }
    return response.listing(db.values("service_records"), filters)


@bp.get("/service-records/<record_id>")
@read_endpoint
def get_service_record(record_id):
    return response.ok(db.require("service_records", record_id))


def _dependent_events(record):
    """Leak events whose evidence chain includes this record."""
    dependents = []
    for event in db.values("leak_events"):
        if event["triggering_service_record_id"] == record["id"]:
            dependents.append(event)
        elif record["leak_event_id"] and event["id"] == record["leak_event_id"]:
            dependents.append(event)
    return dependents


@bp.post("/service-records/<record_id>/void")
@endpoint([COMPLIANCE_MANAGER])
def void_service_record(record_id):
    payload = validate.body()
    void_reason_code = validate.req_str(payload, "void_reason_code")
    record = db.require("service_records", record_id)
    if record["voided"]:
        raise ApiError("ERR_SERVICE_RECORD_ALREADY_VOIDED")

    clock = db.now()
    # PRD 3.8: the retention clock must not yet have been reached.
    if record["retention_until"] <= clock:
        raise ApiError("ERR_VOID_NOT_PERMITTED")
    dependent_events = _dependent_events(record)
    dependent_event_ids = {event["id"] for event in dependent_events}
    for test in db.values("verification_tests"):
        if test["leak_event_id"] in dependent_event_ids and test["result"] == "PASS":
            raise ApiError("ERR_VOID_NOT_PERMITTED")
    triggered = [
        event for event in db.values("leak_events")
        if event["triggering_service_record_id"] == record["id"]
    ]
    for event in triggered:
        if event["repair_attempt_count"] != 0:
            raise ApiError("ERR_VOID_NOT_PERMITTED")
        for test in db.values("verification_tests"):
            if test["leak_event_id"] == event["id"]:
                raise ApiError("ERR_VOID_NOT_PERMITTED")

    system = db.require("systems", record["system_id"])
    record["voided"] = True
    record["voided_at"] = clock
    record["void_reason_code"] = void_reason_code
    db.touch(record)

    cylinder = db.get("cylinders", record["cylinder_id"])
    if cylinder is not None:
        cylinder_snap = db.snapshot(cylinder)
        cylinder["current_contents_lbs"] = util.q1(
            cylinder["current_contents_lbs"]
            + record["refrigerant_added_lbs"]
            - record["refrigerant_recovered_lbs"])
        db.commit(cylinder, cylinder_snap)

    for event in triggered:
        if event["status"] in ("OPEN", "REPAIR_OVERDUE"):
            event_snap = db.snapshot(event)
            event["status"] = "VOIDED"
            event["closed_at"] = clock
            db.commit(event, event_snap)

    ledger.recompute_charge(system)
    ledger.recompute_leak_rate(system)
    posture.system_cascade(system)
    return response.ok(record)
