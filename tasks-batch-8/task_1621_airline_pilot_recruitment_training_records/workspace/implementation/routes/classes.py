"""Equipment, training classes (with the attrition forecast), and enrollments."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    ACTIVE_ENROLLMENT_STATES, MAX_CHECKRIDE_ATTEMPTS,
    bump, get_applicant, get_class, get_enrollment, get_equipment,
    recompute_class, reverse_enrollment_charges, ser_enrollment, ser_equipment,
    ser_training_class, stamp_new, touch,
)
from util import (
    get_body, is_int, is_number, pagination_params, req_str, req_ts, sort_rows,
    success_list, success_object,
)

bp = Blueprint("classes", __name__)

CLASS_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")


# ---- Equipment -----------------------------------------------------------------

@bp.post("/equipment")
def create_equipment():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    sim_cost = body.get("simulator_cost_per_hour_cents")
    if not is_int(sim_cost):
        raise ApiError("ERR_INVALID_REQUEST", "simulator_cost_per_hour_cents must be an integer")
    ioe_hours = body.get("ioe_hours_required")
    if not is_int(ioe_hours):
        raise ApiError("ERR_INVALID_REQUEST", "ioe_hours_required must be an integer")
    landings = body.get("landings_required_90d", 3)
    if not is_int(landings):
        raise ApiError("ERR_INVALID_REQUEST", "landings_required_90d must be an integer")
    equipment = stamp_new({
        "code": code,
        "name": name,
        "simulator_cost_per_hour_cents": sim_cost,
        "ioe_hours_required": ioe_hours,
        "landings_required_90d": landings,
    })
    store.equipment[equipment["id"]] = equipment
    return success_object(ser_equipment(equipment), 201)


@bp.get("/equipment")
def list_equipment():
    require_roles("Recruiter", "CrewScheduler", "TrainingCoordinator", "CheckAirman", "SystemAdmin")
    limit, offset = pagination_params()
    rows = sort_rows(list(store.equipment.values()))
    total = len(rows)
    return success_list([ser_equipment(e) for e in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/equipment/<eid>")
def read_equipment(eid):
    require_roles("Recruiter", "CrewScheduler", "TrainingCoordinator", "CheckAirman", "SystemAdmin")
    return success_object(ser_equipment(get_equipment(eid)))


# ---- Training classes -----------------------------------------------------------

def _validate_class_params(seat_capacity, rate):
    if not is_int(seat_capacity) or seat_capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST", "seat_capacity must be an integer >= 1")
    if not is_number(rate) or rate < 0 or rate > 0.9:
        raise ApiError("ERR_INVALID_REQUEST", "base_attrition_rate must be a decimal in [0, 0.9]")


@bp.post("/training-classes")
def create_class():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    equipment_id = req_str(body, "equipment_id")
    class_date = req_ts(body, "class_date")
    get_equipment(equipment_id)  # body-FK existence (priority 3)
    seat_capacity = body.get("seat_capacity")
    rate = body.get("base_attrition_rate")
    _validate_class_params(seat_capacity, rate)
    cls = stamp_new({
        "equipment_id": equipment_id,
        "class_date": class_date,
        "seat_capacity": seat_capacity,
        "base_attrition_rate": rate,
        "status": "SCHEDULED",
        "active_enrollment_count": 0,
        "confirmed_count": 0,
        "max_seats_sellable": 0,
        "projected_completions_aggregate": 0,
        "projected_completions_walk": 0,
        "over_committed": False,
    })
    store.training_classes[cls["id"]] = cls
    recompute_class(cls)
    return success_object(ser_training_class(cls), 201)


@bp.get("/training-classes")
def list_classes():
    require_roles(*CLASS_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.training_classes.values())
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    if equipment_id is not None:
        rows = [c for c in rows if c["equipment_id"] == equipment_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_rows(rows)
    for c in rows:
        recompute_class(c)  # list reads recompute the forecast per row
    total = len(rows)
    return success_list([ser_training_class(c) for c in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/training-classes/<cid>")
def read_class(cid):
    require_roles(*CLASS_READ_ROLES)
    cls = get_class(cid)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


@bp.post("/training-classes/<cid>/open")
def open_class(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    cls = get_class(cid)
    if cls["status"] != "SCHEDULED":
        raise ApiError("ERR_CLASS_INVALID_STATE",
                       "open requires status SCHEDULED, found %s" % cls["status"])
    if not cls["class_date"] > store.now():
        raise ApiError("ERR_CLASS_INVALID_STATE", "open requires class_date in the future")
    cls["status"] = "OPEN"
    bump(cls)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


@bp.post("/training-classes/<cid>/start")
def start_class(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    cls = get_class(cid)
    if cls["status"] != "OPEN":
        raise ApiError("ERR_CLASS_INVALID_STATE",
                       "start requires status OPEN, found %s" % cls["status"])
    if not store.now() >= cls["class_date"]:
        raise ApiError("ERR_CLASS_INVALID_STATE", "start requires the clock to have reached class_date")
    cls["status"] = "IN_SESSION"
    bump(cls)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


@bp.post("/training-classes/<cid>/complete")
def complete_class(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    cls = get_class(cid)
    if cls["status"] != "IN_SESSION":
        raise ApiError("ERR_CLASS_INVALID_STATE",
                       "complete requires status IN_SESSION, found %s" % cls["status"])
    if any(e["training_class_id"] == cid and e["status"] in ACTIVE_ENROLLMENT_STATES
           for e in store.enrollments.values()):
        raise ApiError("ERR_CLASS_INVALID_STATE", "complete requires no active enrollments")
    cls["status"] = "COMPLETED"
    bump(cls)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


@bp.post("/training-classes/<cid>/cancel")
def cancel_class(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    cls = get_class(cid)
    if cls["status"] not in ("SCHEDULED", "OPEN", "IN_SESSION"):
        raise ApiError("ERR_CLASS_INVALID_STATE",
                       "cancel requires SCHEDULED/OPEN/IN_SESSION, found %s" % cls["status"])
    # Cascade link 1: non-terminal enrollments -> WITHDRAWN (system cascade:
    # updated_at refreshed, no enrollment version bump).
    withdrawn = [e for e in store.enrollments.values()
                 if e["training_class_id"] == cid and e["status"] in ACTIVE_ENROLLMENT_STATES]
    withdrawn.sort(key=lambda e: e.get("_seq", 0))
    for e in withdrawn:
        e["status"] = "WITHDRAWN"
        touch(e)
        # Cascade link 2: REVERSAL entries per non-reversed charge.
        reverse_enrollment_charges(e, "class cancellation reversal")
        # Link 3 (applicant balance recompute) happens inside insert_ledger.
    cls["status"] = "CANCELLED"
    bump(cls)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


@bp.patch("/training-classes/<cid>")
def patch_class(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    cls = get_class(cid)
    if cls["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError("ERR_CLASS_INVALID_STATE",
                       "PATCH requires status SCHEDULED or OPEN, found %s" % cls["status"])
    body = get_body()
    seat_capacity = body.get("seat_capacity")
    rate = body.get("base_attrition_rate")
    expected = body.get("expected_training_class_version")
    # Constraint band (16): field shapes, then the OCC check runs last (18).
    if expected is None or not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_training_class_version is required and must be an integer")
    if seat_capacity is not None and (not is_int(seat_capacity) or seat_capacity < 1):
        raise ApiError("ERR_INVALID_REQUEST", "seat_capacity must be an integer >= 1")
    if rate is not None and (not is_number(rate) or rate < 0 or rate > 0.9):
        raise ApiError("ERR_INVALID_REQUEST", "base_attrition_rate must be a decimal in [0, 0.9]")
    if expected != cls["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_training_class_version %s does not match current version %s"
                       % (expected, cls["version"]))
    if seat_capacity is not None:
        cls["seat_capacity"] = seat_capacity
    if rate is not None:
        cls["base_attrition_rate"] = rate
    bump(cls)
    recompute_class(cls)
    return success_object(ser_training_class(cls))


# ---- Enrollments ----------------------------------------------------------------

@bp.post("/enrollments")
def create_enrollment():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    training_class_id = req_str(body, "training_class_id")
    get_applicant(applicant_id)          # existence, left-to-right per §2.8 list order
    cls = get_class(training_class_id)
    if cls["status"] != "OPEN":
        raise ApiError("ERR_CLASS_NOT_OPEN",
                       "enrollment creation requires class OPEN, found %s" % cls["status"])
    # Constraint band (16): OCC field presence, then duplicate pair.
    expected = body.get("expected_training_class_version")
    if expected is None or not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_training_class_version is required and must be an integer")
    if any(e["applicant_id"] == applicant_id and e["training_class_id"] == training_class_id
           and e["status"] in ACTIVE_ENROLLMENT_STATES for e in store.enrollments.values()):
        raise ApiError("ERR_DUPLICATE_ENROLLMENT",
                       "Applicant already holds a non-terminal enrollment in this class")
    # Seat gate (17), evaluated on pre-request state.
    recompute_class(cls)
    if cls["over_committed"] or cls["active_enrollment_count"] >= cls["max_seats_sellable"]:
        raise ApiError("ERR_CLASS_FULL", "Class seat gate: over_committed or seats exhausted")
    # OCC (18), last, immediately before the write.
    if expected != cls["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_training_class_version %s does not match current version %s"
                       % (expected, cls["version"]))
    enrollment = stamp_new({
        "applicant_id": applicant_id,
        "training_class_id": training_class_id,
        "status": "TENTATIVE",
        "current_phase": "GROUND_SCHOOL",
        "failed_attempts": 0,
        "entered_remediation_at": None,
    })
    store.enrollments[enrollment["id"]] = enrollment
    recompute_class(cls)
    bump(cls)  # successful enrollment creation increments the class version
    return success_object(ser_enrollment(enrollment), 201)


@bp.get("/enrollments")
def list_enrollments():
    require_roles(*CLASS_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.enrollments.values())
    applicant_id = request.args.get("applicant_id")
    training_class_id = request.args.get("training_class_id")
    status = request.args.get("status")
    if applicant_id is not None:
        rows = [e for e in rows if e["applicant_id"] == applicant_id]
    if training_class_id is not None:
        rows = [e for e in rows if e["training_class_id"] == training_class_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_enrollment(e) for e in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/enrollments/<eid>")
def read_enrollment(eid):
    require_roles(*CLASS_READ_ROLES)
    return success_object(ser_enrollment(get_enrollment(eid)))


def _bump_class_for(enrollment):
    cls = store.training_classes.get(enrollment["training_class_id"])
    if cls is not None:
        recompute_class(cls)
        bump(cls)


def _get_enrollment_in_state(eid, allowed, action):
    enrollment = get_enrollment(eid)
    if enrollment["status"] not in allowed:
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE",
                       "%s requires status in {%s}, found %s"
                       % (action, ", ".join(sorted(allowed)), enrollment["status"]))
    return enrollment


@bp.post("/enrollments/<eid>/confirm")
def confirm_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"TENTATIVE"}, "confirm")
    enrollment["status"] = "CONFIRMED"
    bump(enrollment)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/start")
def start_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"CONFIRMED"}, "start")
    cls = store.training_classes.get(enrollment["training_class_id"])
    if cls is None or cls["status"] != "IN_SESSION":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "start requires the class to be IN_SESSION")
    enrollment["status"] = "IN_PROGRESS"
    enrollment["current_phase"] = "GROUND_SCHOOL"
    bump(enrollment)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(
        eid, {"TENTATIVE", "CONFIRMED", "IN_PROGRESS", "REMEDIATION"}, "withdraw")
    enrollment["status"] = "WITHDRAWN"
    bump(enrollment)
    # REVERSAL entries for every non-reversed charge; balance recompute follows.
    reverse_enrollment_charges(enrollment, "withdrawal reversal")
    # SCHEDULED training events -> CANCELLED (system cascade: no version bump).
    # SCHEDULED checkrides are explicitly NOT cancelled.
    for ev in store.training_events.values():
        if ev["enrollment_id"] == eid and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            touch(ev)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/disqualify")
def disqualify_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"IN_PROGRESS", "REMEDIATION"}, "disqualify")
    enrollment["status"] = "DISQUALIFIED"
    bump(enrollment)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/retrain")
def retrain_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"DISQUALIFIED"}, "retrain")
    cls = store.training_classes.get(enrollment["training_class_id"])
    if cls is None or cls["status"] != "IN_SESSION":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "retrain requires the class to be IN_SESSION")
    enrollment["failed_attempts"] = sum(
        1 for c in store.checkrides.values()
        if c["enrollment_id"] == eid and c["status"] == "COMPLETED_FAIL")
    if enrollment["failed_attempts"] > MAX_CHECKRIDE_ATTEMPTS:
        raise ApiError("ERR_MAX_ATTEMPTS_EXCEEDED",
                       "retrain requires failed_attempts <= %d" % MAX_CHECKRIDE_ATTEMPTS)
    enrollment["status"] = "REMEDIATION"
    enrollment["entered_remediation_at"] = store.now()
    bump(enrollment)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/resume")
def resume_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"REMEDIATION"}, "resume")
    marker = enrollment["entered_remediation_at"]
    passing = any(
        ev["enrollment_id"] == eid
        and ev["event_type"] == "MILESTONE"
        and ev["status"] == "COMPLETED"
        and ev["score"] is not None and ev["score"] >= 80
        and (marker is None or ev["updated_at"] > marker)
        for ev in store.training_events.values())
    if not passing:
        raise ApiError("ERR_PHASE_PREREQUISITE_NOT_MET",
                       "resume requires a passing MILESTONE completed after entering remediation")
    enrollment["status"] = "IN_PROGRESS"
    bump(enrollment)
    # Resume does not change class seat counters; class version is untouched.
    cls = store.training_classes.get(enrollment["training_class_id"])
    if cls is not None:
        recompute_class(cls)
    return success_object(ser_enrollment(enrollment))


@bp.post("/enrollments/<eid>/complete")
def complete_enrollment(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    enrollment = _get_enrollment_in_state(eid, {"IN_PROGRESS"}, "complete")
    if enrollment["current_phase"] != "DONE":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "complete requires current_phase DONE")
    if not any(c["enrollment_id"] == eid and c["status"] == "COMPLETED_PASS"
               for c in store.checkrides.values()):
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "complete requires a COMPLETED_PASS checkride")
    enrollment["status"] = "COMPLETED"
    bump(enrollment)
    _bump_class_for(enrollment)
    return success_object(ser_enrollment(enrollment))
