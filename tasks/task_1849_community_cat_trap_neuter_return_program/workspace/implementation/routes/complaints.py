"""Complaint lifecycle endpoints (PRD §3.7).

Working path: OPEN -> IN_MEDIATION -> RESOLVED, both steps by an
AnimalControlOfficer. Escalation path: OPEN -> ESCALATED (HIGH severity only;
escalating a STANDARD complaint requests a transition that does not exist,
ERR_INVALID_STATE), and ESCALATED -> RESOLVED requires the ProgramCoordinator.
An officer resolving an ESCALATED complaint — or a coordinator resolving a
merely-mediated one — requests a transition that does not exist for their
role (ERR_INVALID_STATE). Every complaint status change re-derives the
colony's posture (PRD §2.6).
"""

from flask import Blueprint

from db import db
from errors import invalid_state, not_found
from middleware import require_roles
from response import success_object
from services.colony_service import recompute_colony
from util import public, touch

bp = Blueprint("complaints", __name__)


def get_complaint_or_404(complaint_id):
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        raise not_found("complaint")
    return complaint


def _recompute_colony_of(complaint):
    colony = db.colonies.get(complaint["colony_id"])
    if colony is not None:
        recompute_colony(colony)


@bp.post("/tnr/complaints/<cid>/start-mediation")
@require_roles("AnimalControlOfficer")
def start_mediation(cid, user_id, role):
    complaint = get_complaint_or_404(cid)
    if complaint["status"] != "OPEN":
        raise invalid_state(
            f"Complaint is {complaint['status']}; mediation requires OPEN.")
    complaint["status"] = "IN_MEDIATION"
    touch(complaint)
    _recompute_colony_of(complaint)
    return success_object(public(complaint))


@bp.post("/tnr/complaints/<cid>/escalate")
@require_roles("AnimalControlOfficer")
def escalate(cid, user_id, role):
    complaint = get_complaint_or_404(cid)
    if complaint["status"] != "OPEN":
        raise invalid_state(
            f"Complaint is {complaint['status']}; escalation requires OPEN.")
    if complaint["severity"] != "HIGH":
        raise invalid_state(
            "Only HIGH-severity complaints can be escalated.")
    complaint["status"] = "ESCALATED"
    touch(complaint)
    # The complaint leaves the OPEN set, so the colony posture is re-derived
    # (PRD §2.6: recomputed on every complaint status change).
    _recompute_colony_of(complaint)
    return success_object(public(complaint))


@bp.post("/tnr/complaints/<cid>/resolve")
@require_roles("AnimalControlOfficer", "ProgramCoordinator")
def resolve(cid, user_id, role):
    complaint = get_complaint_or_404(cid)
    allowed = ((complaint["status"] == "IN_MEDIATION" and role == "AnimalControlOfficer")
               or (complaint["status"] == "ESCALATED" and role == "ProgramCoordinator"))
    if not allowed:
        raise invalid_state(
            f"Complaint is {complaint['status']}; no resolve transition exists "
            f"from it for role {role}.")
    complaint["status"] = "RESOLVED"
    touch(complaint)
    _recompute_colony_of(complaint)
    return success_object(public(complaint))
