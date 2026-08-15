"""Incident endpoints: file/list/get, begin-review, resolve, dismiss."""

from flask import Blueprint, request

import clock
import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import body, paginate, require_roles
from response import created, ok
from routes.assignments import get_assignment_or_404
from serializers import incident_view
from services.calc import (
    INCIDENT_PENALTY_FRACTION,
    SCORE_INCIDENT_AT_FAULT,
    adjust_reliability,
    append_ledger,
)
from util import base_entity, round2, touch

bp = Blueprint("incidents", __name__)

SEVERITIES = {"MINOR", "MAJOR", "EMERGENCY"}


def get_incident_or_404(incident_id):
    incident = db.store["incidents"].get(incident_id)
    if incident is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Incident {incident_id} does not exist")
    return incident


@bp.post("/coop/sitting-assignments/<assignment_id>/incidents")
def file_incident(assignment_id):
    user_id, _ = require_roles("Member")
    assignment = get_assignment_or_404(assignment_id)
    data = body()
    severity = data.get("severity")
    if severity not in SEVERITIES:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "severity must be one of MINOR, MAJOR, EMERGENCY"
        )
    description = data.get("description")
    if not isinstance(description, str) or len(description) < 30:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "description must be at least 30 characters"
        )
    vet_involved = data.get("vet_involved")
    if not isinstance(vet_involved, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "vet_involved must be a boolean")
    incident = base_entity()
    incident.update(
        {
            "sitting_assignment_id": assignment["id"],
            "reporter_member_id": user_id,
            "severity": severity,
            "description": description,
            "vet_involved": vet_involved,
            "at_fault_member_id": None,
            "status": "FILED",
            "_decided_at": None,
        }
    )
    db.store["incidents"][incident["id"]] = incident
    return created(incident_view(incident))


@bp.get("/coop/sitting-assignments/<assignment_id>/incidents")
def list_incidents(assignment_id):
    require_roles("CoopAdmin", "Member")
    assignment = get_assignment_or_404(assignment_id)
    items = [
        i
        for i in db.store["incidents"].values()
        if i["sitting_assignment_id"] == assignment["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginate(items, incident_view)


@bp.get("/coop/incidents/<incident_id>")
def get_incident(incident_id):
    require_roles("CoopAdmin", "Member")
    return ok(incident_view(get_incident_or_404(incident_id)))


@bp.post("/coop/incidents/<incident_id>/begin-review")
def begin_review(incident_id):
    require_roles("CoopAdmin")
    incident = get_incident_or_404(incident_id)
    if incident["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Incident must be FILED to begin review")
    incident["status"] = "UNDER_REVIEW"
    touch(incident)
    return ok(incident_view(incident))


@bp.post("/coop/incidents/<incident_id>/resolve")
def resolve_incident(incident_id):
    require_roles("CoopAdmin")
    incident = get_incident_or_404(incident_id)
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Incident must be UNDER_REVIEW to resolve"
        )
    data = body()
    outcome = data.get("outcome")
    if outcome not in ("AT_FAULT", "NO_FAULT"):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "outcome must be AT_FAULT or NO_FAULT"
        )
    if outcome == "AT_FAULT":
        at_fault_member_id = data.get("at_fault_member_id")
        if not isinstance(at_fault_member_id, str) or not at_fault_member_id.strip():
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "at_fault_member_id is required when outcome is AT_FAULT",
            )
        at_fault = db.store["members"].get(at_fault_member_id)
        if at_fault is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "at_fault_member_id does not reference an existing member",
            )
        incident["at_fault_member_id"] = at_fault_member_id
        incident["status"] = "RESOLVED_AT_FAULT"
        incident["_decided_at"] = clock.now()
        touch(incident)
        adjust_reliability(at_fault, SCORE_INCIDENT_AT_FAULT)
        # Ledger penalty only when the assignment is already SETTLED.
        assignment = db.store["assignments"].get(incident["sitting_assignment_id"])
        if (
            assignment is not None
            and assignment["status"] == "SETTLED"
            and assignment["credit_hours_settled"] is not None
        ):
            penalty = round2(
                assignment["credit_hours_settled"] * INCIDENT_PENALTY_FRACTION
            )
            append_ledger(
                at_fault,
                "INCIDENT_PENALTY",
                -penalty,
                assignment_id=assignment["id"],
                memo="Incident at-fault penalty (50% of settled hours)",
            )
    else:
        incident["status"] = "RESOLVED_NO_FAULT"
        incident["_decided_at"] = clock.now()
        touch(incident)
    return ok(incident_view(incident))


@bp.post("/coop/incidents/<incident_id>/dismiss")
def dismiss_incident(incident_id):
    require_roles("CoopAdmin")
    incident = get_incident_or_404(incident_id)
    if incident["status"] not in ("FILED", "UNDER_REVIEW"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Incident must be FILED or UNDER_REVIEW to dismiss",
        )
    incident["status"] = "DISMISSED"
    touch(incident)
    return ok(incident_view(incident))
