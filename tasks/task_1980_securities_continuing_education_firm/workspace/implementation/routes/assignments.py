"""Regulatory element assignments: create / list / get."""

from flask import Blueprint, request

from db import store, base_record, clock_now
from errors import (ApiError, ERR_OPEN_ASSIGNMENT_EXISTS)
from middleware import require_roles, json_body, require_fields
from response import success, paginate
from services import (get_or_404, by_seq, assignment_due_at,
                      assignment_lapse_after)
from util import require_int, view
from routes.enrollments import _check_rep_active

bp = Blueprint("assignments", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/regulatory-assignments")
@require_roles("TrainingAdmin")
def create_assignment():
    body = json_body()
    rep = None
    if body.get("rep_id") is not None:
        rep = get_or_404(store.representatives, body["rep_id"], "Representative")
    require_fields(body, "rep_id", "cycle_year")
    cycle_year = require_int(body["cycle_year"], "cycle_year")
    # Registration standing (assignment creation requires ACTIVE).
    _check_rep_active(rep)
    # At most one open (non-COMPLETED) assignment per rep.
    for a in store.assignments.values():
        if a["rep_id"] == rep["id"] and a["assignment_status"] in (
                "ASSIGNED", "OVERDUE", "LAPSED"):
            raise ApiError(ERR_OPEN_ASSIGNMENT_EXISTS, 409,
                           "Representative already has an open regulatory "
                           "assignment")
    created = clock_now()
    due_at = assignment_due_at(created)
    rec = base_record()
    rec.update({
        "rep_id": rep["id"],
        "cycle_year": cycle_year,
        "assignment_status": "ASSIGNED",
        "due_at": due_at,
        "lapse_after": assignment_lapse_after(due_at),
        "enrollment_id": None,
        "completed_at": None,
    })
    store.assignments[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/regulatory-assignments")
@require_roles(*ANY)
def list_assignments():
    items = by_seq(store.assignments.values())
    for param in ("rep_id", "assignment_status", "enrollment_id"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    items = sorted(items, key=lambda a: (a["created_at"], a["_seq"]))
    page, pagination = paginate(items)
    return success([view(a) for a in page], is_list=True, pagination=pagination)


@bp.get("/regulatory-assignments/<assignmentId>")
@require_roles(*ANY)
def get_assignment(assignmentId):
    rec = get_or_404(store.assignments, assignmentId, "RegulatoryAssignment")
    return success(view(rec))
