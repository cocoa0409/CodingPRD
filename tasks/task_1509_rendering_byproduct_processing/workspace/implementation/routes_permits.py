"""CompliancePermit and OdorEvent endpoints."""
from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_date, v_datetime, ok, view, stamp_new, touch,
                    paginate, sorted_items, get_or_404, fail, iso_z)
from logic import (posture_gate, active_permit, current_settlement,
                   plant_suspend, recompute_posture_after_permit_fix,
                   SEVERITY_PENALTY, RESTRICTED_THRESHOLD)

bp = Blueprint("permits", __name__)


# ---------------- permits ----------------

@bp.post("/rendering/permits")
def create_permit():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    permit_number = v_str(b, "permit_number")
    threshold = v_int(b, "odor_event_threshold", minv=1)
    emission = v_num(b, "emission_limit_ppm")
    expires_on = v_date(b, "expires_on")
    require_role(role, "ComplianceOfficer")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    p = {
        "plant_id": plant_id,
        "permit_number": permit_number,
        "odor_event_threshold": threshold,
        "emission_limit_ppm": emission,
        "issued_on": None,
        "expires_on": expires_on,
        "confirmed_violation_count": 0,
        "status": "DRAFT",
    }
    stamp_new(p)
    db.STORES["permits"][p["id"]] = p
    return ok(view(p), 201)


@bp.get("/rendering/permits")
def list_permits():
    caller()
    items = sorted_items("permits", {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    })
    return paginate(items)


@bp.get("/rendering/permits/<pid>")
def get_permit(pid):
    caller()
    return ok(view(get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")), 200)


@bp.post("/rendering/permits/<pid>/submit")
def submit_permit(pid):
    uid, role = caller()
    require_role(role, "ComplianceOfficer")
    p = get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")
    plant = get_or_404("plants", p["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if p["status"] != "DRAFT":
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit must be DRAFT to submit")
    p["status"] = "PENDING_ISSUANCE"
    touch(p)
    return ok(view(p), 200)


@bp.post("/rendering/permits/<pid>/issue")
def issue_permit(pid):
    uid, role = caller()
    require_role(role, "Regulator")
    p = get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")
    plant = get_or_404("plants", p["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if p["status"] != "PENDING_ISSUANCE":
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit must be PENDING_ISSUANCE to issue")
    if p["expires_on"] < iso_z(db.now())[:10]:
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit expiry date has lapsed")
    for other in db.STORES["permits"].values():
        if (other["id"] != p["id"] and other["plant_id"] == p["plant_id"]
                and other["status"] in ("ACTIVE", "SUSPENDED")):
            fail("ERR_DUPLICATE_ACTIVE_PERMIT", 409,
                 "Another permit for this plant is ACTIVE or SUSPENDED")
    p["status"] = "ACTIVE"
    p["issued_on"] = iso_z(db.now())[:10]
    touch(p)
    if plant["posture"] == "SUSPENDED":
        recompute_posture_after_permit_fix(plant)
    return ok(view(p), 200)


@bp.post("/rendering/permits/<pid>/suspend")
def suspend_permit(pid):
    uid, role = caller()
    require_role(role, "Regulator")
    p = get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")
    plant = get_or_404("plants", p["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if p["status"] != "ACTIVE":
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit must be ACTIVE to suspend")
    p["status"] = "SUSPENDED"
    touch(p)
    plant_suspend(plant)
    return ok(view(p), 200)


@bp.post("/rendering/permits/<pid>/reinstate")
def reinstate_permit(pid):
    uid, role = caller()
    require_role(role, "Regulator")
    p = get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")
    plant = get_or_404("plants", p["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if p["status"] != "SUSPENDED":
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit must be SUSPENDED to reinstate")
    if p["expires_on"] < iso_z(db.now())[:10]:
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit expiry date has lapsed")
    p["status"] = "ACTIVE"
    p["confirmed_violation_count"] = 0
    touch(p)
    recompute_posture_after_permit_fix(plant)
    return ok(view(p), 200)


@bp.post("/rendering/permits/<pid>/revoke")
def revoke_permit(pid):
    uid, role = caller()
    require_role(role, "Regulator")
    p = get_or_404("permits", pid, "ERR_PERMIT_NOT_FOUND")
    plant = get_or_404("plants", p["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_PERMIT_INVALID_STATE", 409, "Permit must be ACTIVE or SUSPENDED to revoke")
    was_active = p["status"] == "ACTIVE"
    p["status"] = "REVOKED"
    touch(p)
    if was_active:
        plant_suspend(plant)
    return ok(view(p), 200)


# ---------------- odor events ----------------

@bp.post("/rendering/odor-events")
def create_odor_event():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    reported_at = v_datetime(b, "reported_at")
    location = v_str(b, "location_description")
    severity = v_enum(b, "severity", {"LOW", "MEDIUM", "HIGH"})
    require_role(role, "ComplianceOfficer")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    ev = {
        "plant_id": plant_id,
        "permit_id": None,
        "reported_at": reported_at,
        "location_description": location,
        "severity": severity,
        "reported_by": uid,
        "confirmed_by": None,
        "status": "REPORTED",
    }
    stamp_new(ev)
    db.STORES["odor_events"][ev["id"]] = ev
    return ok(view(ev), 201)


@bp.get("/rendering/odor-events")
def list_odor_events():
    caller()
    items = sorted_items("odor_events", {
        "plant_id": request.args.get("plant_id"),
        "permit_id": request.args.get("permit_id"),
        "status": request.args.get("status"),
    })
    return paginate(items)


@bp.get("/rendering/odor-events/<eid>")
def get_odor_event(eid):
    caller()
    return ok(view(get_or_404("odor_events", eid, "ERR_ODOR_EVENT_NOT_FOUND")), 200)


def _resolve_odor_event(eid, uid, confirm):
    ev = get_or_404("odor_events", eid, "ERR_ODOR_EVENT_NOT_FOUND")
    plant = get_or_404("plants", ev["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if ev["status"] != "REPORTED":
        fail("ERR_ODOR_EVENT_ALREADY_RESOLVED", 409, "Odor event already resolved")
    if ev["reported_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Resolver must differ from reporter")
    return ev, plant


@bp.post("/rendering/odor-events/<eid>/confirm")
def confirm_odor_event(eid):
    uid, role = caller()
    require_role(role, "ComplianceOfficer")
    ev, plant = _resolve_odor_event(eid, uid, True)
    ev["status"] = "CONFIRMED"
    ev["confirmed_by"] = uid
    perm = active_permit(plant["id"])
    ev["permit_id"] = perm["id"] if perm is not None else None
    touch(ev)
    plant["odor_score"] = max(0, plant["odor_score"] - SEVERITY_PENALTY[ev["severity"]])
    if plant["odor_score"] < RESTRICTED_THRESHOLD and plant["posture"] == "OPERATING":
        plant["posture"] = "RESTRICTED"
    touch(plant)
    st = current_settlement(plant)
    if st is not None:
        st["confirmed_odor_events"] += 1
        touch(st)
    if perm is not None:
        perm["confirmed_violation_count"] += 1
        touch(perm)
        if perm["confirmed_violation_count"] >= perm["odor_event_threshold"]:
            perm["status"] = "SUSPENDED"
            touch(perm)
            plant_suspend(plant)
    return ok(view(ev), 200)


@bp.post("/rendering/odor-events/<eid>/dismiss")
def dismiss_odor_event(eid):
    uid, role = caller()
    require_role(role, "ComplianceOfficer")
    ev, plant = _resolve_odor_event(eid, uid, False)
    ev["status"] = "DISMISSED"
    touch(ev)
    return ok(view(ev), 200)
