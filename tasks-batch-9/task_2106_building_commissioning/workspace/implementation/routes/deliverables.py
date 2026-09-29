"""CloseoutDeliverable endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, D, ROLE_CONTRACTOR, ROLE_CX_AUTHORITY, ROLE_DESIGN_TEAM, ROLE_OWNER_REP,
    actor, authenticate, body_json, bump_project, clock, db, fail, new_row, num, ok,
    ok_list, paginate, public, q, sorted_rows, touch, v_enum, v_int, v_string,
)
from finders import get_deliverable, get_equipment, get_project

bp = Blueprint("deliverables", __name__)


@bp.post("/closeout-deliverables")
def create_deliverable():
    authenticate([ROLE_CONTRACTOR, ROLE_DESIGN_TEAM])
    body = body_json()
    project_id = v_string(body, "project_id")
    deliverable_kind = v_enum(body, "deliverable_kind", calc.DELIVERABLE_KINDS)
    title = v_string(body, "title")
    equipment_id = v_string(body, "equipment_id", required=False, default=None)
    required_attendee_count = v_int(
        body, "required_attendee_count", required=False, default=0, minimum=0)

    get_project(project_id)
    equipment_row = get_equipment(equipment_id) if equipment_id is not None else None
    if equipment_row is not None and equipment_row["project_id"] != project_id:
        fail("ERR_PROJECT_SCOPE_MISMATCH",
             "The equipment unit belongs to a different engagement.")

    row = new_row(db.deliverables, {
        "project_id": project_id,
        "equipment_id": equipment_id,
        "deliverable_kind": deliverable_kind,
        "title": title,
        "required_attendee_count": required_attendee_count,
        "attendee_count": 0,
        "duration_minutes": 0,
        "session_start": None,
        "status": "PLANNED",
        "delivered_by_user_id": None,
        "accepted_by_user_id": None,
        "coverage_ratio": 0,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/closeout-deliverables")
def list_deliverables():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.deliverables.values()))
    for param in ("project_id", "equipment_id", "deliverable_kind", "status"):
        value = q(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/closeout-deliverables/<deliverable_id>")
def read_deliverable(deliverable_id):
    authenticate(ALL_ROLES)
    return ok(public(get_deliverable(deliverable_id)))


@bp.post("/closeout-deliverables/<deliverable_id>/deliver")
def deliver(deliverable_id):
    authenticate([ROLE_CONTRACTOR, ROLE_DESIGN_TEAM])
    row = get_deliverable(deliverable_id)
    body = body_json()
    attendee_count = v_int(body, "attendee_count")
    duration_minutes = v_int(body, "duration_minutes")

    if row["status"] not in ("PLANNED", "RETURNED"):
        fail("ERR_INVALID_STATE", "Only a PLANNED or RETURNED deliverable may be delivered.")

    row["status"] = "DELIVERED"
    row["delivered_by_user_id"] = actor()
    row["attendee_count"] = attendee_count
    row["duration_minutes"] = duration_minutes
    row["session_start"] = clock.now_iso()
    row["coverage_ratio"] = num(
        calc.compute_coverage_ratio(row["required_attendee_count"], attendee_count))
    touch(row)
    services.reconcile()
    return ok(public(row))


@bp.post("/closeout-deliverables/<deliverable_id>/accept")
def accept(deliverable_id):
    authenticate([ROLE_CX_AUTHORITY, ROLE_OWNER_REP])
    row = get_deliverable(deliverable_id)
    body = body_json()
    v_string(body, "attestation_note")

    project = db.projects.get(row["project_id"])
    if project["readiness_posture"] == "FROZEN":
        fail("ERR_PROJECT_FROZEN", "The engagement is FROZEN.")
    if row["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Only a DELIVERED deliverable may be accepted.")
    if actor() == row["delivered_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The acceptor may not be the deliverer.")
    if row["deliverable_kind"] == "TRAINING_SESSION":
        if D(str(row["coverage_ratio"])) < calc.TRAINING_COVERAGE_MIN:
            fail("ERR_TRAINING_COVERAGE_INSUFFICIENT",
                 "coverage_ratio %s is below 0.80." % row["coverage_ratio"])

    row["status"] = "ACCEPTED"
    row["accepted_by_user_id"] = actor()
    touch(row)
    bump_project(project)
    services.reconcile()
    return ok(public(row))


@bp.post("/closeout-deliverables/<deliverable_id>/return")
def return_deliverable(deliverable_id):
    authenticate([ROLE_CX_AUTHORITY])
    row = get_deliverable(deliverable_id)
    body = body_json()
    v_string(body, "reason")

    if row["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Only a DELIVERED deliverable may be returned.")

    project = db.projects.get(row["project_id"])
    row["status"] = "RETURNED"
    row["delivered_by_user_id"] = None
    touch(row)
    bump_project(project)
    services.reconcile()
    return ok(public(row))
