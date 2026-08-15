"""Corrective-action rework loop (PRD §3.5)."""
import db
from errors import (ApiError, ERR_CORRECTIVE_ACTION_STATE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_INVALID_REQUEST, forbidden_ownership)
from services.common import touch, refresh_posture


def submit(ca, lab, user_id, resolution_note):
    if ca["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_CORRECTIVE_ACTION_STATE,
                       "Corrective action must be OPEN or REOPENED to submit", 409)
    if user_id != lab["pi_worker_id"]:
        raise forbidden_ownership("Corrective action must be submitted by the lab's PI")
    ca["status"] = "SUBMITTED"
    ca["resolution_note"] = resolution_note
    touch(ca)
    refresh_posture(lab)
    return ca


def verify(ca, lab, inspection, user_id, decision):
    if ca["status"] != "SUBMITTED":
        raise ApiError(ERR_CORRECTIVE_ACTION_STATE,
                       "Corrective action must be SUBMITTED to verify", 409)
    # Segregation of duties: verifying inspector must differ from the inspector
    # who completed the parent inspection.
    if user_id == inspection["completed_by_inspector_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Verifying inspector must differ from the completing inspector", 403)
    if decision == "APPROVE":
        ca["status"] = "VERIFIED"
        ca["verified_by"] = user_id
    else:  # REJECT
        ca["status"] = "REOPENED"
    touch(ca)
    refresh_posture(lab)
    return ca


def validate_decision(body):
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT", 400)
    return decision
