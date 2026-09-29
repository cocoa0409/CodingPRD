"""Fit-out projects, phase packages and base-building capacity reservations
(PRD 3.5, 3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import db
import helpers
import queries
import response
import serializers
import validation
from errors import fail
from util import dec, q2

bp = Blueprint("delivery", __name__)

ZERO = Decimal("0.00")
CONVERTED_STATES = ("CONVERSION_APPROVED", "CONVERSION_COMPLETE")
QUIESCE_BLOCKING = ("SCHEDULED", "VIBRATION_HOLD", "BLOCKED", "IN_PROGRESS")
VIBRATION_SCAN_STATUSES = ("SCHEDULED", "VIBRATION_HOLD", "BLOCKED", "IN_PROGRESS")
BUFFER = timedelta(hours=constants.VIBRATION_BUFFER_HOURS)


# --------------------------------------------------------------- fit-out projects
@bp.post("/fit-out-projects")
def create_project():
    body = validation.body()
    lease_id = validation.req_id(body, "lease_id")
    floor_id = validation.req_id(body, "floor_id")
    fields = {
        "design_exhaust_cfm": validation.req_num(body, "design_exhaust_cfm", gt=0),
        "design_power_kw": validation.req_num(body, "design_power_kw", gt=0),
        "scope_summary": validation.req_str(body, "scope_summary"),
    }
    auth.require(constants.ROLE_LANDLORD)

    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    helpers.fetch(db.floors, floor_id, "ERR_FLOOR_NOT_FOUND")
    if floor_id != lease["premises_floor_id"]:
        fail("ERR_FLOOR_NOT_IN_PREMISES")
    if lease["status"] not in ("TERMS_ACCEPTED", "EXECUTED", "ACTIVE"):
        fail("ERR_INVALID_LEASE_STATE")

    tenant = queries.tenant_of_lease(lease)
    scripts = list(tenant["required_commissioning_scripts"]) if tenant else []
    fields.update({
        "lease_id": lease["id"],
        "floor_id": floor_id,
        "permit_status": "P_UNPERMITTED",
        "construction_status": "C_NOT_STARTED",
        "required_commissioning_scripts": scripts,
        "permit_applied_at": None,
        "permit_issued_at": None,
        "accepted_at": None,
    })
    record = db.create(db.projects, fields)
    return response.created(serializers.project(record))


@bp.get("/fit-out-projects/<project_id>")
def get_project(project_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT, constants.ROLE_AHJ, constants.ROLE_CX)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    auth.guard_project(project, user_id, role)
    return response.ok(serializers.project(project))


@bp.get("/fit-out-projects")
def list_projects():
    limit, offset = validation.pagination()
    filters = {
        "lease_id": validation.query_str("lease_id"),
        "floor_id": validation.query_str("floor_id"),
        "permit_status": validation.query_enum("permit_status", constants.PERMIT_STATUSES_PROJECT),
        "construction_status": validation.query_enum("construction_status", constants.CONSTRUCTION_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT,
                 constants.ROLE_AHJ, constants.ROLE_CX)
    records = helpers.filtered(db.ordered(db.projects.values()), filters)
    return helpers.page(records, serializers.project, limit, offset)


@bp.post("/fit-out-projects/<project_id>/permit-application")
def apply_for_permit(project_id):
    auth.require(constants.ROLE_LANDLORD)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    if project["permit_status"] != "P_UNPERMITTED":
        fail("ERR_INVALID_PERMIT_STATE")
    lease = queries.lease_of_project(project)
    if lease is None or lease["status"] not in ("EXECUTED", "ACTIVE"):
        fail("ERR_INVALID_LEASE_STATE")
    building = queries.building_of_project(project)
    if building is None or building["suitability_state"] not in CONVERTED_STATES:
        fail("ERR_BUILDING_NOT_CONVERSION_APPROVED")
    exhaust = queries.lab_exhaust_item(building["id"])
    if exhaust is None or exhaust["status"] != "COMPLETE":
        fail("ERR_EXHAUST_SCOPE_INCOMPLETE")

    project["permit_status"] = "P_APPLIED"
    project["permit_applied_at"] = clock.now()
    db.touch(project)
    return response.ok(serializers.project(project))


@bp.post("/fit-out-projects/<project_id>/permit-decision")
def decide_permit(project_id):
    body = validation.body()
    validation.req_enum(body, "decision", ["ISSUE"])
    validation.raw_opt_str(body, "decision_note")
    auth.require(constants.ROLE_AHJ)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    if project["permit_status"] != "P_APPLIED":
        fail("ERR_INVALID_PERMIT_STATE")

    project["permit_status"] = "P_ISSUED"
    project["permit_issued_at"] = clock.now()
    db.touch(project)
    return response.ok(serializers.project(project))


@bp.post("/fit-out-projects/<project_id>/construction-milestone")
def construction_milestone(project_id):
    body = validation.body()
    validation.req_enum(body, "milestone", ["SUBSTANTIAL_COMPLETION"])
    auth.require(constants.ROLE_LANDLORD)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    if project["construction_status"] != "C_IN_PROGRESS":
        fail("ERR_INVALID_PROJECT_STATE")
    phases = queries.phases_of_project(project["id"])
    if any(p["status"] in QUIESCE_BLOCKING for p in phases) \
            or not any(p["status"] == "COMPLETE" for p in phases):
        fail("ERR_PHASES_NOT_QUIESCED")

    project["construction_status"] = "C_SUBSTANTIAL_COMPLETION"
    db.touch(project)
    return response.ok(serializers.project(project))


# --------------------------------------------------------------- phase packages
@bp.post("/fit-out-projects/<project_id>/phase-packages")
def create_phase(project_id):
    body = validation.body()
    fields = {
        "sequence_no": validation.req_int(body, "sequence_no", ge=1),
        "premium_class": validation.req_enum(body, "premium_class", constants.PREMIUM_CLASSES),
        "work_class": validation.req_enum(body, "work_class", constants.WORK_CLASSES),
        "hard_cost_usd": validation.req_num(body, "hard_cost_usd", gt=0),
        "restoration_cost_usd": validation.req_num(body, "restoration_cost_usd", ge=0),
    }
    predecessor_phase_id = validation.opt_id(body, "predecessor_phase_id")
    affected_amenity_id = validation.opt_id(body, "affected_amenity_id")
    auth.require(constants.ROLE_LANDLORD)

    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    predecessor = None
    if predecessor_phase_id is not None:
        predecessor = helpers.fetch(db.phases, predecessor_phase_id, "ERR_PHASE_NOT_FOUND")
    if affected_amenity_id is not None:
        helpers.fetch(db.amenities, affected_amenity_id, "ERR_AMENITY_NOT_FOUND")

    if predecessor is not None and predecessor["project_id"] != project["id"]:
        fail("ERR_PREDECESSOR_NOT_IN_PROJECT")
    for existing in queries.phases_of_project(project["id"]):
        if existing["sequence_no"] == fields["sequence_no"]:
            fail("ERR_DUPLICATE_PHASE_SEQUENCE")
    if fields["work_class"] == "SHUTDOWN_REQUIRED" and affected_amenity_id is None:
        fail("ERR_SHUTDOWN_AMENITY_REQUIRED")

    fields.update({
        "project_id": project["id"],
        "predecessor_phase_id": predecessor_phase_id,
        "affected_amenity_id": affected_amenity_id,
        "window_start": None,
        "window_end": None,
        "status": "DRAFT",
        "prior_status": None,
        "hold_reason": None,
        "ti_eligible_usd": ZERO,
        "ti_committed_usd": ZERO,
        "ti_disbursed_usd": ZERO,
    })
    record = db.create(db.phases, fields)
    return response.created(serializers.phase(record))


@bp.get("/phase-packages/<phase_id>")
def get_phase(phase_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT, constants.ROLE_CX)
    phase = helpers.fetch(db.phases, phase_id, "ERR_PHASE_NOT_FOUND")
    auth.guard_by_project_id(phase["project_id"], user_id, role)
    return response.ok(serializers.phase(phase))


@bp.get("/phase-packages")
def list_phases():
    limit, offset = validation.pagination()
    filters = {
        "project_id": validation.query_str("project_id"),
        "predecessor_phase_id": validation.query_str("predecessor_phase_id"),
        "affected_amenity_id": validation.query_str("affected_amenity_id"),
        "status": validation.query_enum("status", constants.PHASE_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT,
                 constants.ROLE_CX)
    records = helpers.filtered(db.ordered(db.phases.values()), filters)
    return helpers.page(records, serializers.phase, limit, offset)


def _vibration_conflict(phase, window_start, window_end):
    """PRD 3.6: same floor plate, buffered closed-interval test, one side generating."""
    project = db.projects.get(phase["project_id"])
    if project is None:
        return False
    floor_id = project["floor_id"]
    for other in db.phases.values():
        if other["id"] == phase["id"]:
            continue
        if other["status"] not in VIBRATION_SCAN_STATUSES:
            continue
        other_project = db.projects.get(other["project_id"])
        if other_project is None or other_project["floor_id"] != floor_id:
            continue
        if phase["work_class"] != "VIBRATION_GENERATING" \
                and other["work_class"] != "VIBRATION_GENERATING":
            continue
        if other["window_start"] is None or other["window_end"] is None:
            continue
        if window_start <= other["window_end"] + BUFFER \
                and other["window_start"] <= window_end + BUFFER:
            return True
    return False


def _shutdown_conflict(phase, window_start, window_end):
    if phase["work_class"] != "SHUTDOWN_REQUIRED" or phase["affected_amenity_id"] is None:
        return False
    for allocation in queries.allocations_of_amenity(phase["affected_amenity_id"]):
        if allocation["status"] != "CONFIRMED":
            continue
        if allocation["window_start"] < window_end and window_start < allocation["window_end"]:
            return True
    return False


@bp.post("/phase-packages/<phase_id>/schedule")
def schedule_phase(phase_id):
    body = validation.body()
    window_start = validation.req_dt(body, "window_start")
    window_end = validation.req_dt(body, "window_end")
    auth.require(constants.ROLE_LANDLORD)
    phase = helpers.fetch(db.phases, phase_id, "ERR_PHASE_NOT_FOUND")

    if phase["status"] not in ("DRAFT", "SCHEDULED", "VIBRATION_HOLD"):
        fail("ERR_INVALID_PHASE_STATE")
    if window_start >= window_end:
        fail("ERR_INVALID_WINDOW")
    if _vibration_conflict(phase, window_start, window_end):
        fail("ERR_VIBRATION_WINDOW_CONFLICT")

    project = db.projects.get(phase["project_id"])
    lease = queries.lease_of_project(project) if project is not None else None
    if lease is None or lease["executed_at"] is None \
            or window_start < lease["executed_at"] or window_end > lease["delivery_deadline"]:
        fail("ERR_WINDOW_OUTSIDE_DELIVERY_TERM")
    if _shutdown_conflict(phase, window_start, window_end):
        fail("ERR_SHUTDOWN_CONFLICTS_AMENITY")

    was_held = phase["status"] == "VIBRATION_HOLD"
    phase["window_start"] = window_start
    phase["window_end"] = window_end
    phase["status"] = "SCHEDULED"
    phase["hold_reason"] = None
    db.touch(phase)
    if was_held:
        cascades.release_hold(phase)
    return response.ok(serializers.phase(phase))


@bp.post("/phase-packages/<phase_id>/hold")
def hold_phase(phase_id):
    body = validation.body()
    hold_reason = validation.raw_opt_str(body, "hold_reason")
    auth.require(constants.ROLE_ENGINEER)
    phase = helpers.fetch(db.phases, phase_id, "ERR_PHASE_NOT_FOUND")

    if phase["status"] != "SCHEDULED":
        fail("ERR_INVALID_PHASE_STATE")
    if helpers.blank(hold_reason):
        fail("ERR_HOLD_REASON_REQUIRED")

    cascades.apply_hold(phase, hold_reason)
    return response.ok(serializers.phase(phase))


@bp.post("/phase-packages/<phase_id>/progress")
def progress_phase(phase_id):
    body = validation.body()
    target_status = validation.req_enum(body, "target_status", ["IN_PROGRESS", "COMPLETE"])
    auth.require(constants.ROLE_LANDLORD)
    phase = helpers.fetch(db.phases, phase_id, "ERR_PHASE_NOT_FOUND")
    project = db.projects.get(phase["project_id"])

    if target_status == "IN_PROGRESS" and phase["status"] != "SCHEDULED":
        fail("ERR_INVALID_PHASE_STATE")
    if target_status == "COMPLETE" and phase["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_PHASE_STATE")
    if target_status == "IN_PROGRESS":
        if project is None or project["permit_status"] != "P_ISSUED":
            fail("ERR_PROJECT_NOT_PERMITTED")
        if phase["predecessor_phase_id"] is not None:
            predecessor = db.phases.get(phase["predecessor_phase_id"])
            if predecessor is None or predecessor["status"] != "COMPLETE":
                fail("ERR_PREDECESSOR_NOT_COMPLETE")

    if target_status == "IN_PROGRESS":
        phase["status"] = "IN_PROGRESS"
        db.touch(phase)
        if project is not None and project["construction_status"] == "C_NOT_STARTED":
            project["construction_status"] = "C_IN_PROGRESS"
            db.touch(project)
        return response.ok(serializers.phase(phase))

    phase["status"] = "COMPLETE"
    eligible = calc.phase_ti_eligible(phase)
    phase["ti_eligible_usd"] = eligible
    lease = queries.lease_of_project(project) if project is not None else None
    if lease is not None:
        committed = min(eligible, dec(lease["ti_uncommitted_usd"]))
        if committed < 0:
            committed = ZERO
        phase["ti_committed_usd"] = q2(committed)
        lease["ti_uncommitted_usd"] = q2(dec(lease["ti_uncommitted_usd"]) - committed)
        lease["ti_committed_usd"] = q2(dec(lease["ti_committed_usd"]) + committed)
        db.touch(lease)
    db.touch(phase)
    return response.ok(serializers.phase(phase))


# ------------------------------------------------------- capacity reservations
@bp.post("/capacity-reservations")
def create_reservation():
    body = validation.body()
    project_id = validation.req_id(body, "project_id")
    exhaust_cfm = validation.req_num(body, "exhaust_cfm", gt=0)
    power_kw = validation.req_num(body, "power_kw", gt=0)
    expected_building_version = validation.req_int(body, "expected_building_version")
    auth.require(constants.ROLE_LANDLORD)

    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    building = queries.building_of_project(project)
    if building is None or expected_building_version != building["version"]:
        fail("ERR_STALE_BUILDING_VERSION")
    if project["permit_status"] != "P_ISSUED":
        fail("ERR_PROJECT_NOT_PERMITTED")

    pools = calc.building_pools(building)
    if exhaust_cfm > pools["exhaust_available_cfm"]:
        fail("ERR_EXHAUST_CAPACITY_EXCEEDED")
    if power_kw > pools["power_available_kw"]:
        fail("ERR_POWER_CAPACITY_EXCEEDED")

    record = db.create(db.reservations, {
        "project_id": project["id"],
        "building_id": building["id"],
        "exhaust_cfm": exhaust_cfm,
        "power_kw": power_kw,
        "status": "RESERVED",
    })
    db.touch(building)
    return response.created(serializers.reservation(record))


@bp.get("/capacity-reservations/<reservation_id>")
def get_reservation(reservation_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT)
    record = helpers.fetch(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    auth.guard_by_project_id(record["project_id"], user_id, role)
    return response.ok(serializers.reservation(record))


@bp.get("/capacity-reservations")
def list_reservations():
    limit, offset = validation.pagination()
    filters = {
        "project_id": validation.query_str("project_id"),
        "building_id": validation.query_str("building_id"),
        "status": validation.query_enum("status", constants.RESERVATION_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    records = helpers.filtered(db.ordered(db.reservations.values()), filters)
    return helpers.page(records, serializers.reservation, limit, offset)


@bp.post("/capacity-reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    auth.require(constants.ROLE_LANDLORD)
    record = helpers.fetch(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    if record["status"] != "RESERVED":
        fail("ERR_INVALID_RESERVATION_STATE")
    record["status"] = "CANCELLED"
    db.touch(record)
    building = db.buildings.get(record["building_id"])
    if building is not None:
        db.touch(building)
    return response.ok(serializers.reservation(record))
