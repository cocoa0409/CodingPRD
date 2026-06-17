"""Concrete & Paving Contractor API — Flask entry point.

Boots with an empty in-memory store on every process start. No seeding.
"""
import os

from flask import Flask, request, g

from db import db, LOCK
from errors import ApiError, err
import errors as E
from response import object_response, error_response
import helpers as H
import calculations as calc
import serializers as S
from middleware import authenticate, require_roles
import util

app = Flask(__name__)

ALL = ("Estimator", "ProjectManager", "FinanceOfficer", "Inspector")


# ---------------------------------------------------------------------------
# Cross-cutting request handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", str(e)), 422


def get_body():
    """Parse JSON body, tolerating an absent body (treated as empty object)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(E.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_version(body):
    """expected_project_version is a required well-typed field for OCC endpoints (priority 5)."""
    if "expected_project_version" not in body or body.get("expected_project_version") is None:
        raise err(E.ERR_INVALID_REQUEST, "expected_project_version is required")
    val = body.get("expected_project_version")
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(E.ERR_INVALID_REQUEST, "expected_project_version must be an integer")
    return val


# Authenticate every request before routing-specific logic. The _clock and all
# API endpoints require headers; there are no public endpoints.
@app.before_request
def _before():
    authenticate()


# A single global lock makes each request's state mutations atomic.
@app.before_request
def _lock():
    LOCK.acquire()


@app.teardown_request
def _unlock(exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


# ===========================================================================
# PROJECT
# ===========================================================================
@app.post("/projects")
def create_project():
    require_roles("Estimator")
    body = get_body()
    site_name = util.require_string(body, "site_name")
    client_name = util.require_string(body, "client_name")

    p = H.base_record(common_fields=True)
    p.update({
        "site_name": site_name,
        "client_name": client_name,
        "status": "DRAFT",
        "status_before_hold": None,
        "base_contract_amount": 0.00,
        "provisional_contract_value": 0.00,
        "committed_contract_value": 0.00,
        "total_drawn_amount": 0.00,
        "warranty_risk_score": 0,
        "approved_estimate_id": None,
    })
    db.projects[p["id"]] = p
    return object_response(S.project_dict(p), 201)


@app.get("/projects/<pid>")
def get_project(pid):
    require_roles(*ALL)
    p = H.get_project(pid)
    H.recompute_all_derived(p)
    return object_response(S.project_dict(p), 200)


@app.get("/projects")
def list_projects():
    require_roles(*ALL)
    status = request.args.get("status")
    items = list(db.projects.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    for p in items:
        H.recompute_all_derived(p)
    return H.paginate(items, S.project_dict)


@app.post("/projects/<pid>/estimates")
def create_estimate(pid):
    require_roles("Estimator")
    p = H.get_project(pid)
    # state: must be DRAFT to enter ESTIMATING; while ESTIMATING a new estimate supersedes
    if p["status"] not in ("DRAFT", "ESTIMATING"):
        raise err(E.ERR_INVALID_STATE, "Project must be DRAFT or ESTIMATING to create an estimate")
    segments = H.project_segments(pid)
    if len(segments) < 1:
        # PRD §3.2: estimate creation requires DRAFT status AND >= 1 segment; both
        # are part of the transition guard, so a missing segment yields ERR_INVALID_STATE.
        raise err(E.ERR_INVALID_STATE, "Project must have at least one flatwork segment")

    prov_cy = calc.estimate_cubic_yards(segments)
    sqft = calc.total_sqft(segments)
    labor_sub, mat_sub, est_total = calc.estimate_total(segments, prov_cy)

    # supersede any existing DRAFT estimate on the project
    for e in H.project_estimates(pid):
        if e["status"] == "DRAFT":
            e["status"] = "SUPERSEDED"
            H.touch(e)

    e = H.base_record(common_fields=True)
    e.update({
        "project_id": pid,
        "provisional_cubic_yards": prov_cy,
        "total_sqft": sqft,
        "labor_subtotal": labor_sub,
        "material_subtotal": mat_sub,
        "estimate_total": est_total,
        "status": "DRAFT",
    })
    db.estimates[e["id"]] = e

    p["status"] = "ESTIMATING"
    H.touch(p)
    return object_response(S.estimate_dict(e), 201)


@app.get("/projects/<pid>/estimates")
def list_estimates(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_estimates(pid), S.estimate_dict)


@app.post("/projects/<pid>/approve-estimate")
def approve_estimate(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    body = get_body()
    estimate_id = util.require_string(body, "estimate_id")
    expected = require_version(body)

    if p["status"] != "ESTIMATING":
        raise err(E.ERR_INVALID_STATE, "Project must be ESTIMATING to approve an estimate")

    # OCC check (priority 8)
    if expected != p["version"]:
        raise err(E.ERR_STALE_PROJECT_VERSION, "expected_project_version does not match")

    est = db.estimates.get(estimate_id)
    if est is None or est["project_id"] != pid:
        raise err(E.ERR_INVALID_STATE, "Estimate does not belong to this project")
    if est["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Estimate is not in DRAFT")

    est["status"] = "APPROVED"
    H.touch(est)
    # supersede any OTHER DRAFT estimate
    for other in H.project_estimates(pid):
        if other["id"] != est["id"] and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            H.touch(other)

    p["approved_estimate_id"] = est["id"]
    p["base_contract_amount"] = est["estimate_total"]
    H.recompute_contract_values(p)
    p["status"] = "APPROVED"
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/reject")
def reject_project(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] != "ESTIMATING":
        raise err(E.ERR_INVALID_STATE, "Project must be ESTIMATING to reject")
    p["status"] = "REJECTED"
    for e in H.project_estimates(pid):
        if e["status"] == "DRAFT":
            e["status"] = "SUPERSEDED"
            H.touch(e)
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/schedule")
def schedule_project(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] != "APPROVED":
        raise err(E.ERR_INVALID_STATE, "Project must be APPROVED to schedule")
    # cross-entity guard (priority 7)
    permits = H.project_permits(pid)
    has_issued = any(x["status"] == "ISSUED" for x in permits)
    has_ordered = any(m["status"] == "ORDERED" for m in H.project_material_orders(pid))
    has_booked = any(a["status"] == "BOOKED" for a in H.project_crew_assignments(pid))
    if not (has_issued and has_ordered and has_booked):
        raise err(E.ERR_PRECONDITION_NOT_MET,
                  "Schedule requires an ISSUED permit, an ORDERED material order, and a BOOKED crew assignment")
    p["status"] = "SCHEDULED"
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/begin-cure")
def begin_cure(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] != "POURED":
        raise err(E.ERR_INVALID_STATE, "Project must be POURED to begin cure")
    poured = next((m for m in H.project_material_orders(pid)
                   if m["cure_window_end"] is not None), None)
    if poured is None:
        raise err(E.ERR_PRECONDITION_NOT_MET, "Poured material order has no cure window")
    p["status"] = "CURING"
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/complete")
def complete_project(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] != "CURING":
        raise err(E.ERR_INVALID_STATE, "Project must be CURING to complete")
    # precondition: ACTIVE warranty (priority 7)
    has_active_warranty = any(w["status"] == "ACTIVE" for w in H.project_warranties(pid))
    # temporal: cure window must have elapsed (priority 10)
    poured = next((m for m in H.project_material_orders(pid)
                   if m["cure_window_end"] is not None), None)
    # Per priority ordering, precondition (7) is checked before temporal (10).
    if not has_active_warranty:
        raise err(E.ERR_PRECONDITION_NOT_MET, "Project must have an ACTIVE warranty to complete")
    if poured is None or db.logical_now() < poured["cure_window_end"]:
        raise err(E.ERR_CURE_WINDOW_NOT_ELAPSED, "Cure window has not elapsed")

    p["status"] = "COMPLETED"
    # release every still-BOOKED crew assignment
    for a in H.project_crew_assignments(pid):
        if a["status"] == "BOOKED":
            a["status"] = "RELEASED"
            H.touch(a)
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/hold")
def hold_project(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] not in ("APPROVED", "SCHEDULED"):
        raise err(E.ERR_INVALID_STATE, "Project must be APPROVED or SCHEDULED to hold")
    p["status_before_hold"] = p["status"]
    p["status"] = "ON_HOLD"
    H.touch(p)
    return object_response(S.project_dict(p), 200)


@app.post("/projects/<pid>/resume")
def resume_project(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    if p["status"] != "ON_HOLD":
        raise err(E.ERR_INVALID_STATE, "Project must be ON_HOLD to resume")
    p["status"] = p["status_before_hold"]
    p["status_before_hold"] = None
    H.touch(p)
    return object_response(S.project_dict(p), 200)


# ===========================================================================
# FLATWORK SEGMENT
# ===========================================================================
@app.post("/projects/<pid>/segments")
def create_segment(pid):
    require_roles("Estimator")
    p = H.get_project(pid)
    body = get_body()
    label = util.require_string(body, "label")
    area = util.require_number(body, "area_sqft")
    thickness = util.require_number(body, "thickness_in")
    finish = util.optional_enum(body, "finish_grade",
                                {"BROOM", "EXPOSED_AGGREGATE", "STAMPED"}, "BROOM")
    reinf = util.optional_enum(body, "reinforcement", {"NONE", "MESH", "REBAR"}, "NONE")
    if area <= 0:
        raise err(E.ERR_INVALID_REQUEST, "area_sqft must be > 0")
    if thickness <= 0:
        raise err(E.ERR_INVALID_REQUEST, "thickness_in must be > 0")
    # state guard: segments are added to a DRAFT project
    if p["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Segments may only be added to a DRAFT project")

    s = H.base_record(common_fields=True)
    s.update({
        "project_id": pid,
        "label": label,
        "area_sqft": area,
        "thickness_in": thickness,
        "finish_grade": finish,
        "reinforcement": reinf,
    })
    db.segments[s["id"]] = s
    H.touch(p)
    return object_response(S.segment_dict(s), 201)


@app.get("/projects/<pid>/segments")
def list_segments(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_segments(pid), S.segment_dict)


# ===========================================================================
# PERMIT
# ===========================================================================
@app.post("/projects/<pid>/permits")
def create_permit(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    body = get_body()
    jurisdiction = util.require_string(body, "jurisdiction")
    permit_number = util.require_string(body, "permit_number")

    perm = H.base_record(common_fields=True)
    perm.update({
        "project_id": pid,
        "jurisdiction": jurisdiction,
        "permit_number": permit_number,
        "status": "APPLIED",
    })
    db.permits[perm["id"]] = perm
    H.touch(p)
    return object_response(S.permit_dict(perm), 201)


@app.get("/projects/<pid>/permits")
def list_permits(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_permits(pid), S.permit_dict)


@app.post("/permits/<permit_id>/issue")
def issue_permit(permit_id):
    require_roles("Inspector")
    perm = H.get_permit(permit_id)
    if perm["status"] != "APPLIED":
        raise err(E.ERR_INVALID_STATE, "Permit must be APPLIED to issue")
    perm["status"] = "ISSUED"
    H.touch(perm)
    return object_response(S.permit_dict(perm), 200)


@app.post("/permits/<permit_id>/close")
def close_permit(permit_id):
    require_roles("Inspector")
    perm = H.get_permit(permit_id)
    if perm["status"] != "ISSUED":
        raise err(E.ERR_INVALID_STATE, "Permit must be ISSUED to close")
    project = H.get_project(perm["project_id"])
    if project["status"] != "COMPLETED":
        raise err(E.ERR_PRECONDITION_NOT_MET, "Project must be COMPLETED to close the permit")
    perm["status"] = "CLOSED"
    H.touch(perm)
    return object_response(S.permit_dict(perm), 200)


@app.post("/permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    require_roles("Inspector")
    perm = H.get_permit(permit_id)
    if perm["status"] not in ("APPLIED", "ISSUED"):
        raise err(E.ERR_INVALID_STATE, "Permit must be APPLIED or ISSUED to revoke")
    perm["status"] = "REVOKED"
    H.touch(perm)
    project = db.projects.get(perm["project_id"])
    if project is not None and project["status"] == "SCHEDULED":
        project["status_before_hold"] = "SCHEDULED"
        project["status"] = "ON_HOLD"
        H.touch(project)
    return object_response(S.permit_dict(perm), 200)


# ===========================================================================
# MATERIAL ORDER
# ===========================================================================
@app.post("/projects/<pid>/material-orders")
def create_material_order(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    body = get_body()
    mix_type = util.require_enum(body, "mix_type", {"STANDARD", "HIGH_EARLY", "FIBER"})
    pour_start = util.parse_dt(body.get("pour_scheduled_start"), "pour_scheduled_start")
    duration = util.require_number(body, "pour_duration_hours")
    if duration <= 0:
        raise err(E.ERR_INVALID_REQUEST, "pour_duration_hours must be > 0")

    segments = H.project_segments(pid)
    order_cy = calc.order_cubic_yards(segments)

    m = H.base_record(common_fields=True)
    m.update({
        "project_id": pid,
        "mix_type": mix_type,
        "order_cubic_yards": order_cy,
        "pour_scheduled_start": pour_start,
        "pour_duration_hours": duration,
        "pour_completed_at": None,
        "cure_window_end": None,
        "status": "ORDERED",
        "weather_violation": False,
    })
    db.material_orders[m["id"]] = m
    H.touch(p)
    return object_response(S.material_order_dict(m), 201)


@app.get("/projects/<pid>/material-orders")
def list_material_orders(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_material_orders(pid), S.material_order_dict)


@app.get("/material-orders/<mid>")
def get_material_order_route(mid):
    require_roles(*ALL)
    m = H.get_material_order(mid)
    return object_response(S.material_order_dict(m), 200)


@app.post("/material-orders/<mid>/start-pour")
def start_pour(mid):
    require_roles("ProjectManager")
    m = H.get_material_order(mid)
    body = get_body()
    force = util.require_bool_optional(body, "force_override", False)

    project = H.get_project(m["project_id"])
    if m["status"] != "ORDERED":
        raise err(E.ERR_INVALID_STATE, "MaterialOrder must be ORDERED to start the pour")
    if project["status"] != "SCHEDULED":
        raise err(E.ERR_INVALID_STATE, "Project must be SCHEDULED to start the pour")

    # weather gate (priority 9): in-window readings out of range
    from datetime import timedelta
    win_start = m["pour_scheduled_start"]
    win_end = win_start + timedelta(hours=m["pour_duration_hours"])
    out_of_range = False
    for w in H.order_weather_readings(mid):
        ra = w["reading_at"]
        if win_start <= ra < win_end:
            if w["temp_f"] < 40 or w["temp_f"] > 90 or w["precip_pct"] >= 50:
                out_of_range = True
                break
    if out_of_range and not force:
        raise err(E.ERR_WEATHER_OUT_OF_RANGE, "An in-window weather reading is out of range")
    if out_of_range and force:
        m["weather_violation"] = True

    m["status"] = "POURING"
    H.touch(m)
    return object_response(S.material_order_dict(m), 200)


@app.post("/material-orders/<mid>/complete-pour")
def complete_pour(mid):
    require_roles("ProjectManager")
    m = H.get_material_order(mid)
    body = get_body()
    completed_at = util.parse_dt(body.get("completed_at"), "completed_at")

    project = H.get_project(m["project_id"])
    if m["status"] != "POURING":
        raise err(E.ERR_INVALID_STATE, "MaterialOrder must be POURING to complete the pour")

    # LINK 1
    m["pour_completed_at"] = completed_at
    m["cure_window_end"] = calc.cure_window_end(completed_at, m["mix_type"])
    m["status"] = "POURED"
    H.touch(m)
    # LINK 2: bubble Project SCHEDULED -> POURED
    if project["status"] == "SCHEDULED":
        project["status"] = "POURED"
    # LINK 3: recompute warranty_risk_score
    H.recompute_warranty_risk(project)
    H.touch(project)
    return object_response(S.material_order_dict(m), 200)


@app.post("/material-orders/<mid>/cancel")
def cancel_material_order(mid):
    require_roles("ProjectManager")
    m = H.get_material_order(mid)
    if m["status"] != "ORDERED":
        raise err(E.ERR_INVALID_STATE, "MaterialOrder must be ORDERED to cancel")
    m["status"] = "CANCELLED"
    H.touch(m)
    return object_response(S.material_order_dict(m), 200)


# ===========================================================================
# WEATHER READING
# ===========================================================================
@app.post("/material-orders/<mid>/weather-readings")
def create_weather_reading(mid):
    require_roles("ProjectManager", "Inspector")
    m = H.get_material_order(mid)
    body = get_body()
    reading_at = util.parse_dt(body.get("reading_at"), "reading_at")
    temp_f = util.require_number(body, "temp_f")
    precip = util.require_number(body, "precip_pct")
    if precip < 0 or precip > 100:
        raise err(E.ERR_INVALID_REQUEST, "precip_pct must be between 0 and 100")

    w = H.base_record(common_fields=False)
    w.update({
        "material_order_id": mid,
        "reading_at": reading_at,
        "temp_f": temp_f,
        "precip_pct": precip,
    })
    db.weather_readings[w["id"]] = w
    return object_response(S.weather_reading_dict(w), 201)


@app.get("/material-orders/<mid>/weather-readings")
def list_weather_readings(mid):
    require_roles(*ALL)
    H.get_material_order(mid)
    return H.paginate(H.order_weather_readings(mid), S.weather_reading_dict)


# ===========================================================================
# CREW / EQUIPMENT POOLS
# ===========================================================================
@app.post("/crews")
def create_crew():
    require_roles("ProjectManager")
    body = get_body()
    crew_name = util.require_string(body, "crew_name")
    skill = util.require_enum(body, "skill", {"FLATWORK", "FINISHING", "PAVING"})
    headcount = util.require_int(body, "headcount")
    if headcount < 1:
        raise err(E.ERR_INVALID_REQUEST, "headcount must be >= 1")
    c = H.base_record(common_fields=True)
    c.update({"crew_name": crew_name, "skill": skill, "headcount": headcount})
    db.crews[c["id"]] = c
    return object_response(S.crew_dict(c), 201)


@app.get("/crews/<cid>")
def get_crew_route(cid):
    require_roles(*ALL)
    c = H.get_crew(cid)
    return object_response(S.crew_dict(c), 200)


@app.post("/equipment")
def create_equipment():
    require_roles("ProjectManager")
    body = get_body()
    asset_name = util.require_string(body, "asset_name")
    asset_type = util.require_enum(body, "asset_type",
                                   {"PUMP_TRUCK", "POWER_TROWEL", "SCREED", "MIXER"})
    e = H.base_record(common_fields=True)
    e.update({"asset_name": asset_name, "asset_type": asset_type})
    db.equipment[e["id"]] = e
    return object_response(S.equipment_dict(e), 201)


@app.get("/equipment/<eid>")
def get_equipment_route(eid):
    require_roles(*ALL)
    e = H.get_equipment(eid)
    return object_response(S.equipment_dict(e), 200)


# ===========================================================================
# CREW ASSIGNMENT
# ===========================================================================
def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start,a_end) intersects [b_start,b_end)."""
    return a_start < b_end and b_start < a_end


@app.post("/projects/<pid>/crew-assignments")
def create_crew_assignment(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    body = get_body()
    crew_id = util.require_string(body, "crew_id")
    equipment_id = util.optional_string(body, "equipment_id", None)
    window_start = util.parse_dt(body.get("window_start"), "window_start")
    window_end = util.parse_dt(body.get("window_end"), "window_end")
    if not (window_end > window_start):
        raise err(E.ERR_INVALID_REQUEST, "window_end must be strictly after window_start")

    # body FK existence (priority 4)
    if crew_id not in db.crews:
        raise err(E.ERR_FK_NOT_FOUND, "crew_id references a non-existent crew")
    if equipment_id is not None and equipment_id not in db.equipment:
        raise err(E.ERR_FK_NOT_FOUND, "equipment_id references a non-existent equipment")

    # crew double-booking (priority 11): half-open overlap against same-crew BOOKED
    for a in db.crew_assignments.values():
        if a["status"] == "BOOKED" and a["crew_id"] == crew_id:
            if _overlaps(window_start, window_end, a["window_start"], a["window_end"]):
                raise err(E.ERR_CREW_DOUBLE_BOOKED, "Crew is already booked for an overlapping window")

    # equipment double-booking (priority 12): buffered by 2h on each side
    if equipment_id is not None:
        from datetime import timedelta
        buf = timedelta(hours=2)
        for a in db.crew_assignments.values():
            if a["status"] == "BOOKED" and a["equipment_id"] == equipment_id:
                b_start = a["window_start"] - buf
                b_end = a["window_end"] + buf
                if _overlaps(window_start, window_end, b_start, b_end):
                    raise err(E.ERR_EQUIPMENT_DOUBLE_BOOKED,
                              "Equipment is already booked for an overlapping (buffered) window")

    a = H.base_record(common_fields=True)
    a.update({
        "project_id": pid,
        "crew_id": crew_id,
        "equipment_id": equipment_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "BOOKED",
    })
    db.crew_assignments[a["id"]] = a
    H.touch(p)
    return object_response(S.crew_assignment_dict(a), 201)


@app.get("/projects/<pid>/crew-assignments")
def list_project_crew_assignments(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_crew_assignments(pid), S.crew_assignment_dict)


@app.get("/crew-assignments")
def list_crew_assignments():
    require_roles(*ALL)
    crew_id = request.args.get("crew_id")
    equipment_id = request.args.get("equipment_id")
    items = list(db.crew_assignments.values())
    if crew_id is not None:
        items = [a for a in items if a["crew_id"] == crew_id]
    if equipment_id is not None:
        items = [a for a in items if a["equipment_id"] == equipment_id]
    return H.paginate(items, S.crew_assignment_dict)


@app.get("/crew-assignments/<aid>")
def get_crew_assignment_route(aid):
    require_roles(*ALL)
    a = H.get_crew_assignment(aid)
    return object_response(S.crew_assignment_dict(a), 200)


@app.post("/crew-assignments/<aid>/release")
def release_crew_assignment(aid):
    require_roles("ProjectManager")
    a = H.get_crew_assignment(aid)
    if a["status"] != "BOOKED":
        raise err(E.ERR_INVALID_STATE, "CrewAssignment must be BOOKED to release")
    a["status"] = "RELEASED"
    H.touch(a)
    return object_response(S.crew_assignment_dict(a), 200)


# ===========================================================================
# CHANGE ORDER
# ===========================================================================
@app.post("/projects/<pid>/change-orders")
def create_change_order(pid):
    require_roles("FinanceOfficer")
    p = H.get_project(pid)
    body = get_body()
    description = util.require_string(body, "description")
    delta_amount = util.require_number(body, "delta_amount")
    delta_sqft = util.optional_number(body, "delta_sqft", 0)

    c = H.base_record(common_fields=True)
    c.update({
        "project_id": pid,
        "description": description,
        "delta_amount": util.money(delta_amount),
        "delta_sqft": delta_sqft,
        "status": "SUBMITTED",
        "submitted_by_user_id": g.user_id,
    })
    db.change_orders[c["id"]] = c
    H.touch(p)
    return object_response(S.change_order_dict(c), 201)


@app.get("/projects/<pid>/change-orders")
def list_change_orders(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_change_orders(pid), S.change_order_dict)


@app.post("/change-orders/<cid>/start-review")
def start_review(cid):
    require_roles("FinanceOfficer")
    c = H.get_change_order(cid)
    if c["status"] != "SUBMITTED":
        raise err(E.ERR_INVALID_STATE, "ChangeOrder must be SUBMITTED to start review")
    c["status"] = "UNDER_REVIEW"
    H.touch(c)
    p = db.projects[c["project_id"]]
    H.recompute_contract_values(p)
    H.touch(p)
    return object_response(S.change_order_dict(c), 200)


@app.post("/change-orders/<cid>/request-revision")
def request_revision(cid):
    require_roles("FinanceOfficer")
    c = H.get_change_order(cid)
    if c["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "ChangeOrder must be UNDER_REVIEW to request revision")
    c["status"] = "REVISION_REQUESTED"
    H.touch(c)
    p = db.projects[c["project_id"]]
    H.recompute_contract_values(p)
    H.touch(p)
    return object_response(S.change_order_dict(c), 200)


@app.post("/change-orders/<cid>/resubmit")
def resubmit_change_order(cid):
    require_roles("FinanceOfficer")
    c = H.get_change_order(cid)
    body = get_body()
    delta_amount = util.require_number(body, "delta_amount")
    delta_sqft = util.optional_number(body, "delta_sqft", 0)
    if c["status"] != "REVISION_REQUESTED":
        raise err(E.ERR_INVALID_STATE, "ChangeOrder must be REVISION_REQUESTED to resubmit")
    c["status"] = "SUBMITTED"
    c["delta_amount"] = util.money(delta_amount)
    c["delta_sqft"] = delta_sqft
    c["submitted_by_user_id"] = g.user_id
    H.touch(c)
    return object_response(S.change_order_dict(c), 200)


@app.post("/change-orders/<cid>/approve")
def approve_change_order(cid):
    require_roles("FinanceOfficer")
    c = H.get_change_order(cid)
    body = get_body()
    expected = require_version(body)
    p = db.projects[c["project_id"]]

    if c["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "ChangeOrder must be UNDER_REVIEW to approve")
    if p["status"] not in ("APPROVED", "SCHEDULED", "ON_HOLD"):
        raise err(E.ERR_INVALID_STATE, "Project must be APPROVED, SCHEDULED, or ON_HOLD to approve a change order")
    # OCC (priority 8)
    if expected != p["version"]:
        raise err(E.ERR_STALE_PROJECT_VERSION, "expected_project_version does not match")
    # segregation of duties (priority 13)
    for d in H.project_draws(p["id"]):
        if d["status"] == "RELEASED" and d["released_by_user_id"] == g.user_id:
            raise err(E.ERR_SEGREGATION_VIOLATION,
                      "Approver cannot be a user who released a draw on this project")

    c["status"] = "APPROVED"
    H.touch(c)
    H.recompute_contract_values(p)
    H.touch(p)
    return object_response(S.change_order_dict(c), 200)


@app.post("/change-orders/<cid>/reject")
def reject_change_order(cid):
    require_roles("FinanceOfficer")
    c = H.get_change_order(cid)
    if c["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "ChangeOrder must be UNDER_REVIEW to reject")
    c["status"] = "REJECTED"
    H.touch(c)
    p = db.projects[c["project_id"]]
    H.recompute_contract_values(p)
    H.touch(p)
    return object_response(S.change_order_dict(c), 200)


# ===========================================================================
# DRAW
# ===========================================================================
@app.post("/projects/<pid>/draws")
def create_draw(pid):
    require_roles("FinanceOfficer")
    p = H.get_project(pid)
    body = get_body()
    draw_type = util.require_enum(body, "draw_type", {"DEPOSIT", "PROGRESS", "FINAL"})
    amount = util.require_number(body, "amount")
    if amount <= 0:
        raise err(E.ERR_INVALID_REQUEST, "amount must be > 0")

    d = H.base_record(common_fields=True)
    d.update({
        "project_id": pid,
        "draw_type": draw_type,
        "amount": util.money(amount),
        "status": "REQUESTED",
        "released_by_user_id": None,
    })
    db.draws[d["id"]] = d
    H.touch(p)
    return object_response(S.draw_dict(d), 201)


@app.get("/projects/<pid>/draws")
def list_draws(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_draws(pid), S.draw_dict)


@app.post("/draws/<did>/release")
def release_draw(did):
    require_roles("FinanceOfficer")
    d = H.get_draw(did)
    body = get_body()
    expected = require_version(body)
    p = db.projects[d["project_id"]]

    if d["status"] != "REQUESTED":
        raise err(E.ERR_INVALID_STATE, "Draw must be REQUESTED to release")
    if p["status"] not in ("APPROVED", "SCHEDULED", "POURED", "CURING"):
        raise err(E.ERR_INVALID_STATE,
                  "Project must be APPROVED, SCHEDULED, POURED, or CURING to release a draw")
    # OCC (priority 8)
    if expected != p["version"]:
        raise err(E.ERR_STALE_PROJECT_VERSION, "expected_project_version does not match")

    # segregation of duties (priority 13): releaser != submitter of any APPROVED CO
    for co in H.project_change_orders(p["id"]):
        if co["status"] == "APPROVED" and co["submitted_by_user_id"] == g.user_id:
            raise err(E.ERR_SEGREGATION_VIOLATION,
                      "Releaser cannot be the submitter of an APPROVED change order on this project")

    # waterfall cap (priority 14)
    cap = calc.draw_cap(d["draw_type"], p["committed_contract_value"])
    if util.money(p["total_drawn_amount"] + d["amount"]) > cap:
        raise err(E.ERR_DRAW_EXCEEDS_CONTRACT, "Draw would exceed the contract draw cap")

    # sequence rules (priority 15)
    if d["draw_type"] == "DEPOSIT":
        for other in H.project_draws(p["id"]):
            if other["id"] != d["id"] and other["draw_type"] == "DEPOSIT" and other["status"] == "RELEASED":
                raise err(E.ERR_DRAW_SEQUENCE_INVALID, "A DEPOSIT draw has already been released")
    if d["draw_type"] == "FINAL":
        if p["status"] != "CURING":
            raise err(E.ERR_DRAW_SEQUENCE_INVALID, "FINAL draw requires the project to be CURING")
        for other in H.project_draws(p["id"]):
            if other["id"] != d["id"] and other["status"] not in ("VOIDED", "RELEASED"):
                raise err(E.ERR_DRAW_SEQUENCE_INVALID,
                          "Every other non-VOIDED draw must be RELEASED before a FINAL draw")

    d["status"] = "RELEASED"
    d["released_by_user_id"] = g.user_id
    H.touch(d)
    H.recompute_total_drawn(p)
    H.touch(p)
    return object_response(S.draw_dict(d), 200)


@app.post("/draws/<did>/void")
def void_draw(did):
    require_roles("FinanceOfficer")
    d = H.get_draw(did)
    if d["status"] != "REQUESTED":
        raise err(E.ERR_INVALID_STATE, "Draw must be REQUESTED to void")
    d["status"] = "VOIDED"
    H.touch(d)
    return object_response(S.draw_dict(d), 200)


# ===========================================================================
# WARRANTY
# ===========================================================================
@app.post("/projects/<pid>/warranties")
def create_warranty(pid):
    require_roles("ProjectManager")
    p = H.get_project(pid)
    body = get_body()
    term_months = util.require_int(body, "term_months")
    if term_months < 1:
        raise err(E.ERR_INVALID_REQUEST, "term_months must be >= 1")
    # approved-or-later project
    if p["status"] not in ("APPROVED", "SCHEDULED", "POURED", "CURING", "COMPLETED", "ON_HOLD"):
        raise err(E.ERR_INVALID_STATE, "Project must be approved-or-later to issue a warranty")

    w = H.base_record(common_fields=True)
    w.update({
        "project_id": pid,
        "term_months": term_months,
        "defect_claims_count": 0,
        "status": "ACTIVE",
    })
    db.warranties[w["id"]] = w
    H.touch(p)
    return object_response(S.warranty_dict(w), 201)


@app.get("/projects/<pid>/warranties")
def list_warranties(pid):
    require_roles(*ALL)
    H.get_project(pid)
    return H.paginate(H.project_warranties(pid), S.warranty_dict)


@app.post("/warranties/<wid>/claims")
def file_claim(wid):
    require_roles("Inspector")
    w = H.get_warranty(wid)
    body = get_body()
    util.optional_string(body, "defect_note", None)  # validated if present
    if w["status"] not in ("ACTIVE", "CLAIM_OPEN"):
        raise err(E.ERR_INVALID_STATE, "Warranty must be ACTIVE or CLAIM_OPEN to file a claim")
    p = db.projects[w["project_id"]]
    if p["status"] != "COMPLETED":
        raise err(E.ERR_PRECONDITION_NOT_MET, "Project must be COMPLETED to file a defect claim")

    w["defect_claims_count"] += 1
    w["status"] = "CLAIM_OPEN"
    H.touch(w)
    H.recompute_warranty_risk(p)
    H.touch(p)
    return object_response(S.warranty_dict(w), 200)


@app.post("/warranties/<wid>/resolve-claim")
def resolve_claim(wid):
    require_roles("Inspector")
    w = H.get_warranty(wid)
    if w["status"] != "CLAIM_OPEN":
        raise err(E.ERR_INVALID_STATE, "Warranty must be CLAIM_OPEN to resolve a claim")
    w["status"] = "ACTIVE"
    H.touch(w)
    return object_response(S.warranty_dict(w), 200)


@app.post("/warranties/<wid>/void")
def void_warranty(wid):
    require_roles("ProjectManager")
    w = H.get_warranty(wid)
    if w["status"] not in ("ACTIVE", "CLAIM_OPEN"):
        raise err(E.ERR_INVALID_STATE, "Warranty must be ACTIVE or CLAIM_OPEN to void")
    w["status"] = "VOID"
    H.touch(w)
    return object_response(S.warranty_dict(w), 200)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ProjectManager")
    body = get_body()
    instant = util.parse_dt(body.get("to_iso8601"), "to_iso8601")
    db.set_logical_clock(instant)
    return object_response({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
