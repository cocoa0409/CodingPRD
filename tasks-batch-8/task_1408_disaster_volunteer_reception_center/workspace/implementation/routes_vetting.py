"""SkillCredential, BackgroundCheck, and Clearance endpoints."""

from datetime import timedelta

from flask import Blueprint, g

import db
import services as svc
from errors import (
    ERR_CHECK_ALREADY_PENDING,
    ERR_CLEARANCE_ALREADY_ACTIVE,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SOD_CLEARANCE_VIOLATION,
    raise_error,
)
from middleware import authenticate, authorize
from response import success_object
from validation import (
    CLEARANCE_TYPES,
    CREDENTIAL_CLASSES,
    SKILL_CODES,
    check_unknown_fields,
    get_body,
    opt_string,
    req_datetime,
    req_enum,
    req_string,
)
from validators import (
    get_background_check_or_404,
    get_clearance_or_404,
    get_credential_or_404,
    incident_gate,
    load_fk_string,
)

bp = Blueprint("vetting", __name__)

TERMINAL_VOLUNTEER_STATES = ("WITHDRAWN", "REJECTED", "DEMOBILIZED")


# --- SkillCredential ------------------------------------------------------------

@bp.post("/vrc/credentials")
def create_credential():
    authenticate()
    authorize(["IntakeCoordinator", "Volunteer"])
    body = get_body()
    volunteer_id = load_fk_string(body, "volunteer_id", db.volunteers, "Volunteer")
    check_unknown_fields(body, {"volunteer_id", "skill_code", "credential_class", "expires_at", "evidence_notes"})
    if not isinstance(volunteer_id, str) or not volunteer_id:
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "Missing required field: volunteer_id")
    skill_code = req_enum(body, "skill_code", SKILL_CODES)
    credential_class = req_enum(body, "credential_class", CREDENTIAL_CLASSES)
    expires_at = req_datetime(body, "expires_at")
    evidence_notes = opt_string(body, "evidence_notes")
    volunteer = db.volunteers[volunteer_id]
    incident_gate(db.incidents[volunteer["incident_id"]], "credential claim")
    if g.role == "Volunteer" and g.user_id != volunteer_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only claim credentials on their own record")
    rec = svc.create_record(db.credentials, {
        "volunteer_id": volunteer_id,
        "skill_code": skill_code,
        "credential_class": credential_class,
        "evidence_notes": evidence_notes,
        "expires_at": expires_at,
        "status": "CLAIMED",
        "verified_by_user_id": None,
        "verified_at": None,
    })
    return success_object(svc.credential_view(rec), 201)


def _credential_transition_check(cred):
    """Stage 7 state preconditions shared by verify and reject."""
    if cred["status"] not in ("CLAIMED", "EXPIRED"):
        raise_error(ERR_INVALID_STATE, f"Credential must be CLAIMED or EXPIRED (current: {cred['status']})")
    volunteer = db.volunteers[cred["volunteer_id"]]
    if volunteer["status"] in TERMINAL_VOLUNTEER_STATES:
        raise_error(ERR_INVALID_STATE, f"Parent volunteer is {volunteer['status']}; credential adjudication is no longer permitted")
    return volunteer


@bp.post("/vrc/credentials/<credentialId>/verify")
def verify_credential(credentialId):
    authenticate()
    authorize(["VettingOfficer"])
    cred = get_credential_or_404(credentialId)
    get_body()
    volunteer = db.volunteers[cred["volunteer_id"]]
    incident_gate(db.incidents[volunteer["incident_id"]], "credential verification")
    _credential_transition_check(cred)
    cred["status"] = "VERIFIED"
    cred["verified_by_user_id"] = g.user_id
    cred["verified_at"] = db.now()
    svc.touch(cred)
    svc.reeval_volunteer_clearance(volunteer)
    svc.recompute_posture(db.incidents[volunteer["incident_id"]])
    return success_object(svc.credential_view(cred))


@bp.post("/vrc/credentials/<credentialId>/reject")
def reject_credential(credentialId):
    authenticate()
    authorize(["VettingOfficer"])
    cred = get_credential_or_404(credentialId)
    get_body()
    volunteer = db.volunteers[cred["volunteer_id"]]
    incident_gate(db.incidents[volunteer["incident_id"]], "credential rejection")
    _credential_transition_check(cred)
    cred["status"] = "REJECTED"
    svc.touch(cred)
    return success_object(svc.credential_view(cred))


# --- BackgroundCheck --------------------------------------------------------------

@bp.post("/vrc/background-checks")
def create_background_check():
    authenticate()
    authorize(["VettingOfficer"])
    body = get_body()
    volunteer_id = load_fk_string(body, "volunteer_id", db.volunteers, "Volunteer")
    check_unknown_fields(body, {"volunteer_id"})
    if not isinstance(volunteer_id, str) or not volunteer_id:
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "Missing required field: volunteer_id")
    volunteer = db.volunteers[volunteer_id]
    incident_gate(db.incidents[volunteer["incident_id"]], "background check creation")
    if volunteer["status"] not in ("VETTING", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, f"Volunteer must be VETTING or SUSPENDED to open a background check (current: {volunteer['status']})")
    if any(b["volunteer_id"] == volunteer_id and b["status"] == "REQUESTED" for b in db.background_checks.values()):
        raise_error(ERR_CHECK_ALREADY_PENDING, "A REQUESTED background check already exists for this volunteer")
    rec = svc.create_record(db.background_checks, {
        "volunteer_id": volunteer_id,
        "status": "REQUESTED",
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
        "expires_at": None,
    })
    return success_object(svc.background_check_view(rec), 201)


def _adjudication_precheck(check):
    if check["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, f"Background check must be REQUESTED (current: {check['status']})")
    volunteer = db.volunteers[check["volunteer_id"]]
    if g.user_id == volunteer["registered_by_user_id"]:
        raise_error(ERR_SOD_CLEARANCE_VIOLATION, "The operator who registered the volunteer may not adjudicate their background check")
    return volunteer


@bp.post("/vrc/background-checks/<checkId>/clear")
def clear_background_check(checkId):
    authenticate()
    authorize(["VettingOfficer"])
    check = get_background_check_or_404(checkId)
    get_body()
    volunteer = db.volunteers[check["volunteer_id"]]
    incident = db.incidents[volunteer["incident_id"]]
    incident_gate(incident, "background check clearance")
    _adjudication_precheck(check)
    check["status"] = "CLEARED"
    check["adjudicated_by_user_id"] = g.user_id
    check["adjudicated_at"] = db.now()
    check["expires_at"] = db.now() + timedelta(hours=720)
    svc.touch(check)
    svc.reeval_volunteer_clearance(volunteer)
    return success_object(svc.background_check_view(check))


@bp.post("/vrc/background-checks/<checkId>/flag")
def flag_background_check(checkId):
    authenticate()
    authorize(["VettingOfficer"])
    check = get_background_check_or_404(checkId)
    get_body()
    volunteer = db.volunteers[check["volunteer_id"]]
    incident = db.incidents[volunteer["incident_id"]]
    incident_gate(incident, "background check flagging")
    _adjudication_precheck(check)
    check["status"] = "FLAGGED"
    check["adjudicated_by_user_id"] = g.user_id
    check["adjudicated_at"] = db.now()
    svc.touch(check)
    if volunteer["status"] == "VETTING":
        volunteer["status"] = "REJECTED"
        svc.touch(volunteer)
    elif volunteer["status"] in ("CLEARED", "READY", "DEPLOYED"):
        volunteer["status"] = "SUSPENDED"
        svc.touch(volunteer)
        svc.suspension_cascade(volunteer)
    else:
        svc.recompute_posture(incident)
    return success_object(svc.background_check_view(check))


# --- Clearance ----------------------------------------------------------------------

@bp.post("/vrc/clearances")
def create_clearance():
    authenticate()
    authorize(["IntakeCoordinator"])
    body = get_body()
    volunteer_id = load_fk_string(body, "volunteer_id", db.volunteers, "Volunteer")
    check_unknown_fields(body, {"volunteer_id", "clearance_type"})
    if not isinstance(volunteer_id, str) or not volunteer_id:
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "Missing required field: volunteer_id")
    clearance_type = req_enum(body, "clearance_type", CLEARANCE_TYPES)
    volunteer = db.volunteers[volunteer_id]
    incident_gate(db.incidents[volunteer["incident_id"]], "clearance recording")
    if any(
        c["volunteer_id"] == volunteer_id and c["clearance_type"] == clearance_type and c["status"] == "ACTIVE"
        for c in db.clearances.values()
    ):
        raise_error(ERR_CLEARANCE_ALREADY_ACTIVE, "An ACTIVE clearance of this type already exists for the volunteer")
    now = db.now()
    valid_until = now + timedelta(hours=72) if clearance_type == "SAFETY_BRIEFING" else None
    rec = svc.create_record(db.clearances, {
        "volunteer_id": volunteer_id,
        "clearance_type": clearance_type,
        "status": "ACTIVE",
        "completed_at": now,
        "valid_until": valid_until,
        "revoked_reason": None,
    })
    return success_object(svc.clearance_view(rec), 201)


@bp.post("/vrc/clearances/<clearanceId>/revoke")
def revoke_clearance(clearanceId):
    authenticate()
    authorize(["RiskOfficer", "VRCManager"])
    clearance = get_clearance_or_404(clearanceId)
    body = get_body()
    check_unknown_fields(body, {"reason"})
    reason = req_string(body, "reason")
    volunteer = db.volunteers[clearance["volunteer_id"]]
    incident_gate(db.incidents[volunteer["incident_id"]], "clearance revocation")
    if clearance["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"Clearance must be ACTIVE to revoke (current: {clearance['status']})")
    clearance["status"] = "REVOKED"
    clearance["revoked_reason"] = reason
    svc.touch(clearance)
    if clearance["clearance_type"] == "LIABILITY_WAIVER":
        if volunteer["status"] == "READY":
            volunteer["status"] = "CLEARED"
            svc.touch(volunteer)
        elif volunteer["status"] == "DEPLOYED":
            volunteer["status"] = "SUSPENDED"
            svc.touch(volunteer)
            svc.suspension_cascade(volunteer)
    return success_object(svc.clearance_view(clearance))
