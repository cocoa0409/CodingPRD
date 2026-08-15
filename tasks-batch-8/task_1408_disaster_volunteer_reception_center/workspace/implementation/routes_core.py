"""Incident lifecycle, logical clock, and volunteer pipeline endpoints."""

from flask import Blueprint, g

import db
import services as svc
from errors import (
    ERR_INCIDENT_CLOSING_BLOCKED,
    ERR_INVALID_STATE,
    ERR_NO_CREDENTIALS_CLAIMED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OPEN_ASSIGNMENTS,
    ERR_READINESS_INCOMPLETE,
    ERR_STALE_VERSION,
    ERR_UNRETURNED_PPE,
    ERR_VOLUNTEER_BLACKLISTED,
    raise_error,
)
from middleware import ALL_ROLES, authenticate, authorize
from response import paginate, success_list, success_object
from validation import (
    check_unknown_fields,
    get_body,
    opt_string,
    req_datetime,
    req_int,
    req_ppe_stock,
    req_string,
)
from validators import (
    get_incident_or_404,
    get_volunteer_or_404,
    incident_gate,
    load_fk_string,
)

bp = Blueprint("core", __name__)


# --- Incident -----------------------------------------------------------------

@bp.post("/vrc/incidents")
def create_incident():
    authenticate()
    authorize(["VRCManager"])
    body = get_body()
    check_unknown_fields(body, {"name", "ppe_stock"})
    name = req_string(body, "name")
    stock = req_ppe_stock(body, "ppe_stock")
    rec = svc.create_record(db.incidents, {
        "name": name,
        "lifecycle_status": "ACTIVATION",
        "operational_posture": "OPEN",
        "ppe_stock": stock,
        "activated_at": None,
        "demobilized_at": None,
        "closed_at": None,
    })
    return success_object(svc.incident_view(rec), 201)


@bp.get("/vrc/incidents/<incidentId>")
def get_incident(incidentId):
    authenticate()
    authorize(ALL_ROLES)
    inc = get_incident_or_404(incidentId)
    return success_object(svc.incident_view(inc))


@bp.post("/vrc/incidents/<incidentId>/activate")
def activate_incident(incidentId):
    authenticate()
    authorize(["VRCManager"])
    inc = get_incident_or_404(incidentId)
    get_body()
    if inc["lifecycle_status"] != "ACTIVATION":
        raise_error(ERR_INVALID_STATE, "Incident must be in ACTIVATION to activate")
    inc["lifecycle_status"] = "ACTIVE"
    inc["activated_at"] = db.now()
    svc.touch(inc)
    svc.recompute_posture(inc)
    return success_object(svc.incident_view(inc))


@bp.post("/vrc/incidents/<incidentId>/begin-demobilization")
def begin_demobilization(incidentId):
    authenticate()
    authorize(["VRCManager"])
    inc = get_incident_or_404(incidentId)
    get_body()
    if inc["lifecycle_status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Incident must be ACTIVE to begin demobilization")
    for a in db.assignments.values():
        if a["incident_id"] == inc["id"] and a["status"] == "CHECKED_IN":
            raise_error(ERR_OPEN_ASSIGNMENTS, "Assignments remain CHECKED_IN for this incident")
    inc["lifecycle_status"] = "DEMOBILIZATION"
    inc["demobilized_at"] = db.now()
    svc.touch(inc)
    return success_object(svc.incident_view(inc))


@bp.post("/vrc/incidents/<incidentId>/close")
def close_incident(incidentId):
    authenticate()
    authorize(["VRCManager"])
    inc = get_incident_or_404(incidentId)
    get_body()
    if inc["lifecycle_status"] != "DEMOBILIZATION":
        raise_error(ERR_INVALID_STATE, "Incident must be in DEMOBILIZATION to close")
    iid = inc["id"]
    blocked = False
    if any(v["incident_id"] == iid and v["status"] not in ("DEMOBILIZED", "WITHDRAWN", "REJECTED")
           for v in db.volunteers.values()):
        blocked = True
    if any(r["incident_id"] == iid and r["status"] not in ("COMPLETED", "CANCELLED")
           for r in db.support_requests.values()):
        blocked = True
    for a in db.assignments.values():
        if a["incident_id"] != iid:
            continue
        for e in svc.hour_entries_of_assignment(a["id"]):
            if e["status"] not in ("VERIFIED", "REJECTED_FINAL"):
                blocked = True
    incident_volunteer_ids = {v["id"] for v in db.volunteers.values() if v["incident_id"] == iid}
    if any(p["volunteer_id"] in incident_volunteer_ids and p["status"] not in ("RETURNED", "DAMAGED", "LOST")
           for p in db.ppe_issuances.values()):
        blocked = True
    if any(t["incident_id"] == iid and t["status"] not in ("ARRIVED", "CANCELLED")
           for t in db.trips.values()):
        blocked = True
    if any(s["incident_id"] == iid and s["status"] != "CANCELLED" for s in db.shifts.values()):
        blocked = True
    if blocked:
        raise_error(
            ERR_INCIDENT_CLOSING_BLOCKED,
            "Close-out preconditions unmet: non-terminal volunteers, requests, hour entries, PPE issuances, trips, or shifts remain",
        )
    inc["lifecycle_status"] = "CLOSED"
    inc["closed_at"] = db.now()
    svc.touch(inc)
    return success_object(svc.incident_view(inc))


# --- Incident reverse-channel lists ----------------------------------------------

@bp.get("/vrc/incidents/<incidentId>/volunteers")
def list_incident_volunteers(incidentId):
    authenticate()
    authorize(ALL_ROLES)
    inc = get_incident_or_404(incidentId)
    from flask import request
    records = [v for v in db.volunteers.values() if v["incident_id"] == inc["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [v for v in records if v["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.volunteer_view(v) for v in window], page)


@bp.get("/vrc/incidents/<incidentId>/support-requests")
def list_incident_requests(incidentId):
    authenticate()
    authorize(ALL_ROLES)
    inc = get_incident_or_404(incidentId)
    from flask import request
    records = [r for r in db.support_requests.values() if r["incident_id"] == inc["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    criticality = request.args.get("criticality")
    if criticality is not None:
        records = [r for r in records if r["criticality"] == criticality]
    window, page = paginate(records, request.args)
    return success_list([svc.support_request_view(r) for r in window], page)


@bp.get("/vrc/incidents/<incidentId>/shifts")
def list_incident_shifts(incidentId):
    authenticate()
    authorize(ALL_ROLES)
    inc = get_incident_or_404(incidentId)
    from flask import request
    records = [s for s in db.shifts.values() if s["incident_id"] == inc["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    hazard = request.args.get("hazard_level")
    if hazard is not None:
        records = [s for s in records if s["hazard_level"] == hazard]
    site_name = request.args.get("site_name")
    if site_name is not None:
        records = [s for s in records if s["site_name"] == site_name]
    window, page = paginate(records, request.args)
    return success_list([svc.shift_view(s) for s in window], page)


# --- Logical clock -------------------------------------------------------------------

@bp.post("/vrc/_clock/set_current_utc")
def set_clock():
    authenticate()
    authorize(["VRCManager"])
    body = get_body()
    check_unknown_fields(body, {"to_iso8601"})
    target = req_datetime(body, "to_iso8601")
    db.set_clock(target)
    svc.run_clock_sweep()
    return success_object({"current_utc": db.fmt_ts(db.now())})


# --- Volunteer --------------------------------------------------------------------------

@bp.post("/vrc/volunteers")
def create_volunteer():
    authenticate()
    authorize(["IntakeCoordinator", "Volunteer"])
    body = get_body()
    incident_id = load_fk_string(body, "incident_id", db.incidents, "Incident")
    check_unknown_fields(body, {"incident_id", "full_name", "phone", "email", "home_locality"})
    full_name = req_string(body, "full_name")
    phone = req_string(body, "phone")
    email = req_string(body, "email")
    home_locality = req_string(body, "home_locality")
    incident_gate(db.incidents[incident_id], "volunteer registration")
    new_id = db.new_id()
    registered_by = new_id if g.role == "Volunteer" else g.user_id
    rec = {
        "id": new_id,
        "incident_id": incident_id,
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "home_locality": home_locality,
        "status": "REGISTERED",
        "registered_by_user_id": registered_by,
        "recognition_tier": "NONE",
        "demobilized_at": None,
    }
    rec = svc.create_record(db.volunteers, rec)
    return success_object(svc.volunteer_view(rec), 201)


@bp.get("/vrc/volunteers/<volunteerId>")
def get_volunteer(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    return success_object(svc.volunteer_view(v))


@bp.patch("/vrc/volunteers/<volunteerId>")
def patch_volunteer(volunteerId):
    authenticate()
    authorize(["IntakeCoordinator", "Volunteer"])
    v = get_volunteer_or_404(volunteerId)
    body = get_body()
    check_unknown_fields(body, {"expected_volunteer_version", "phone", "email", "home_locality"})
    expected = req_int(body, "expected_volunteer_version")
    phone = opt_string(body, "phone")
    email = opt_string(body, "email")
    home_locality = opt_string(body, "home_locality")
    incident_gate(db.incidents[v["incident_id"]], "volunteer profile edit")
    if v["status"] not in ("REGISTERED", "VETTING", "CLEARED", "READY"):
        raise_error(ERR_INVALID_STATE, f"Volunteer profile may only be edited from REGISTERED, VETTING, CLEARED or READY (current: {v['status']})")
    if expected != v["version"]:
        raise_error(ERR_STALE_VERSION, "expected_volunteer_version does not match the volunteer's current version")
    if g.role == "Volunteer" and g.user_id != v["id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only edit their own record")
    if phone is not None:
        v["phone"] = phone
    if email is not None:
        v["email"] = email
    if home_locality is not None:
        v["home_locality"] = home_locality
    svc.touch(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/submit-for-vetting")
def submit_for_vetting(volunteerId):
    authenticate()
    authorize(["IntakeCoordinator"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "submit-for-vetting")
    if v["status"] != "REGISTERED":
        raise_error(ERR_INVALID_STATE, f"Volunteer must be REGISTERED to submit for vetting (current: {v['status']})")
    if not any(c["volunteer_id"] == v["id"] for c in db.credentials.values()):
        raise_error(ERR_NO_CREDENTIALS_CLAIMED, "Volunteer has no claimed skill credentials")
    v["status"] = "VETTING"
    svc.touch(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/mark-ready")
def mark_ready(volunteerId):
    authenticate()
    authorize(["IntakeCoordinator"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "mark-ready")
    if v["status"] != "CLEARED":
        raise_error(ERR_INVALID_STATE, f"Volunteer must be CLEARED to mark ready (current: {v['status']})")
    missing = []
    if not svc.has_current_briefing(v["id"]):
        missing.append("ACTIVE SAFETY_BRIEFING with valid_until in the future")
    if not svc.has_active_waiver(v["id"]):
        missing.append("ACTIVE LIABILITY_WAIVER")
    if not svc.has_fresh_cleared_bg(v["id"]):
        missing.append("CLEARED unexpired BackgroundCheck")
    if not svc.has_verified_credential(v["id"]):
        missing.append("VERIFIED SkillCredential")
    if missing:
        raise_error(ERR_READINESS_INCOMPLETE, "Readiness prerequisites missing: " + "; ".join(missing))
    v["status"] = "READY"
    svc.touch(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/suspend")
def suspend_volunteer(volunteerId):
    authenticate()
    authorize(["RiskOfficer"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "suspend")
    if v["status"] not in ("VETTING", "CLEARED", "READY", "DEPLOYED"):
        raise_error(ERR_INVALID_STATE, f"Volunteer must be VETTING, CLEARED, READY or DEPLOYED to suspend (current: {v['status']})")
    v["status"] = "SUSPENDED"
    svc.touch(v)
    svc.suspension_cascade(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/reinstate")
def reinstate_volunteer(volunteerId):
    authenticate()
    authorize(["RiskOfficer"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "reinstate")
    if v["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, f"Volunteer must be SUSPENDED to reinstate (current: {v['status']})")
    _, lifetime = svc.risk_scores(v["id"])
    if lifetime >= svc.BLACKLIST_THRESHOLD:
        raise_error(ERR_VOLUNTEER_BLACKLISTED, "Volunteer lifetime risk score is at or above 100")
    if not any(b["volunteer_id"] == v["id"] and b["status"] == "REQUESTED" for b in db.background_checks.values()):
        raise_error(ERR_INVALID_STATE, "A REQUESTED background check must exist for the volunteer to reinstate")
    v["status"] = "VETTING"
    svc.touch(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/withdraw")
def withdraw_volunteer(volunteerId):
    authenticate()
    authorize(["IntakeCoordinator", "Volunteer"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "withdraw")
    if v["status"] not in ("REGISTERED", "VETTING", "CLEARED", "READY"):
        raise_error(ERR_INVALID_STATE, f"Volunteer must be REGISTERED, VETTING, CLEARED or READY to withdraw (current: {v['status']})")
    if g.role == "Volunteer" and g.user_id != v["id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only withdraw themselves")
    v["status"] = "WITHDRAWN"
    svc.touch(v)
    svc.withdraw_cascade(v)
    return success_object(svc.volunteer_view(v))


@bp.post("/vrc/volunteers/<volunteerId>/demobilize")
def demobilize_volunteer(volunteerId):
    authenticate()
    authorize(["VRCManager"])
    v = get_volunteer_or_404(volunteerId)
    get_body()
    incident_gate(db.incidents[v["incident_id"]], "demobilize", demob_allowed=True)
    if v["status"] not in ("CLEARED", "READY", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, f"Volunteer must be CLEARED, READY or SUSPENDED to demobilize (current: {v['status']})")
    if any(a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED", "CHECKED_IN")
           for a in svc.assignments_of_volunteer(v["id"])):
        raise_error(ERR_OPEN_ASSIGNMENTS, "Volunteer has assignments in non-terminal states")
    if any(p["volunteer_id"] == v["id"] and p["status"] == "ISSUED" for p in db.ppe_issuances.values()):
        raise_error(ERR_UNRETURNED_PPE, "Volunteer has PPE issuances still ISSUED")
    v["recognition_tier"] = svc.recognition_tier_for(v)
    v["demobilized_at"] = db.now()
    v["status"] = "DEMOBILIZED"
    svc.touch(v)
    return success_object(svc.volunteer_view(v))


# --- Volunteer reverse-channel lists ---------------------------------------------------------

@bp.get("/vrc/volunteers/<volunteerId>/credentials")
def list_volunteer_credentials(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    from flask import request
    records = [c for c in db.credentials.values() if c["volunteer_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.credential_view(c) for c in window], page)


@bp.get("/vrc/volunteers/<volunteerId>/background-checks")
def list_volunteer_background_checks(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    from flask import request
    records = [b for b in db.background_checks.values() if b["volunteer_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.background_check_view(b) for b in window], page)


@bp.get("/vrc/volunteers/<volunteerId>/clearances")
def list_volunteer_clearances(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    from flask import request
    records = [c for c in db.clearances.values() if c["volunteer_id"] == v["id"]]
    ctype = request.args.get("clearance_type")
    if ctype is not None:
        records = [c for c in records if c["clearance_type"] == ctype]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.clearance_view(c) for c in window], page)


@bp.get("/vrc/volunteers/<volunteerId>/ppe-issuances")
def list_volunteer_ppe(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    from flask import request
    records = [p for p in db.ppe_issuances.values() if p["volunteer_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.ppe_issuance_view(p) for p in window], page)


@bp.get("/vrc/volunteers/<volunteerId>/risk-reports")
def list_volunteer_risk_reports(volunteerId):
    authenticate()
    authorize(ALL_ROLES)
    v = get_volunteer_or_404(volunteerId)
    from flask import request
    records = [r for r in db.risk_reports.values() if r["subject_volunteer_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    severity = request.args.get("severity")
    if severity is not None:
        records = [r for r in records if r["severity"] == severity]
    window, page = paginate(records, request.args)
    return success_list([svc.risk_report_view(r) for r in window], page)
