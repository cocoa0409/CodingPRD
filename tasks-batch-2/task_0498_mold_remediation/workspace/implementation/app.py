"""Mold & Environmental Remediation API — entry point and all routes."""
import os
from flask import Flask, request

from errors import ApiError, err
from response import success_object, success_array, error_response
from auth import authenticate, require_role
from db import db, base_fields, touch
from util import clock, parse_dt, days_between_floor
import validate as V
import serialize as S
import logic as L

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_PROJECT_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", 400, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e)


def auth_and_role(allowed):
    """Run auth then role check; returns (user_id, role)."""
    user_id, role = authenticate()
    require_role(role, allowed)
    return user_id, role


def sorted_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


def filtered_list(records, filters):
    """filters: list of (param_name, record_field). Apply request.args filters."""
    out = records
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            out = [r for r in out if r.get(field) == val]
    return out


ALL_ROLES = {"ProjectManager", "AbatementSupervisor", "LabTech", "Hygienist", "ComplianceOfficer"}


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_and_role({"ComplianceOfficer"})
    body = V.get_body()
    dt = V.parse_required_dt(body, "to_iso8601")
    clock.set(dt)
    return success_object({"current_utc": _fmt(dt)})


def _fmt(dt):
    from util import _fmt_ms
    return _fmt_ms(dt)


# ===========================================================================
# Workers
# ===========================================================================
@app.route("/api/workers", methods=["POST"])
def create_worker():
    auth_and_role({"ProjectManager", "ComplianceOfficer"})
    body = V.get_body()
    V.require_fields(body, ["full_name", "cert_type", "cert_expires_at", "ppe_fit_test_at"])
    V.valid_enum(body, "cert_type", {"ASBESTOS", "LEAD", "MOLD", "HYGIENIST"})
    if not isinstance(body["full_name"], str) or not body["full_name"]:
        raise err("ERR_INVALID_REQUEST", "full_name must be a non-empty string")
    if V.parse_required_dt(body, "cert_expires_at") is None:
        raise err("ERR_INVALID_REQUEST", "cert_expires_at invalid")
    if V.parse_required_dt(body, "ppe_fit_test_at") is None:
        raise err("ERR_INVALID_REQUEST", "ppe_fit_test_at invalid")
    rec = base_fields()
    rec.update({
        "full_name": body["full_name"],
        "cert_type": body["cert_type"],
        "cert_expires_at": body["cert_expires_at"],
        "ppe_fit_test_at": body["ppe_fit_test_at"],
    })
    db.workers[rec["id"]] = rec
    return success_object(S.ser_worker(rec), 201)


@app.route("/api/workers", methods=["GET"])
def list_workers():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.workers.values()), [("cert_type", "cert_type")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_worker(r) for r in page], limit, offset, total)


@app.route("/api/workers/<wid>", methods=["GET"])
def get_worker(wid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("worker", wid)
    return success_object(S.ser_worker(rec))


# ===========================================================================
# Projects
# ===========================================================================
@app.route("/api/projects", methods=["POST"])
def create_project():
    auth_and_role({"ProjectManager"})
    body = V.get_body()
    V.require_fields(body, ["site_name", "hazard_class", "structure_sqft", "jurisdiction_code"])
    V.valid_enum(body, "hazard_class", {"ASBESTOS", "LEAD", "MOLD"})
    sqft = body["structure_sqft"]
    if not isinstance(sqft, int) or isinstance(sqft, bool) or sqft <= 0:
        raise err("ERR_INVALID_REQUEST", "structure_sqft must be a positive integer")
    if not isinstance(body["site_name"], str) or not body["site_name"]:
        raise err("ERR_INVALID_REQUEST", "site_name must be a non-empty string")
    if not isinstance(body["jurisdiction_code"], str) or not body["jurisdiction_code"]:
        raise err("ERR_INVALID_REQUEST", "jurisdiction_code must be a non-empty string")
    rec = base_fields()
    rec.update({
        "site_name": body["site_name"],
        "hazard_class": body["hazard_class"],
        "structure_sqft": sqft,
        "jurisdiction_code": body["jurisdiction_code"],
        "status": "OPEN",
        "posture": "ASSESSMENT",
        "open_finding_count": 0,
    })
    rec["neshap_required"] = L.compute_neshap_required(rec)
    db.projects[rec["id"]] = rec
    return success_object(S.ser_project(rec), 201)


@app.route("/api/projects", methods=["GET"])
def list_projects():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.projects.values()),
                         [("hazard_class", "hazard_class"), ("posture", "posture")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_project(r) for r in page], limit, offset, total)


@app.route("/api/projects/<pid>", methods=["GET"])
def get_project(pid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("project", pid)
    return success_object(S.ser_project(rec))


@app.route("/api/projects/<pid>/signoff", methods=["POST"])
def project_signoff(pid):
    auth_and_role({"Hygienist"})
    p = V.get_or_404("project", pid)
    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Project is not OPEN")
    if p["posture"] != "VERIFIED":
        raise err("ERR_PROJECT_NOT_VERIFIED", "Project posture is not VERIFIED")
    if p["open_finding_count"] != 0:
        raise err("ERR_OPEN_FINDINGS_REMAIN", "Project has open findings")
    p["status"] = "SIGNED_OFF"
    touch(p)
    return success_object(S.ser_project(p))


@app.route("/api/projects/<pid>/abandon", methods=["POST"])
def project_abandon(pid):
    auth_and_role({"ProjectManager"})
    p = V.get_or_404("project", pid)
    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Project is not OPEN")
    orders = L.project_orders(pid)
    if any(o["status"] in ("IN_PROGRESS", "REOPENED") for o in orders):
        raise err("ERR_ABATEMENT_IN_PROGRESS", "An abatement order is in progress")
    # Cascade: PLANNED orders -> CANCELLED; their ACTIVE assignments -> RELEASED
    for o in orders:
        if o["status"] == "PLANNED":
            o["status"] = "CANCELLED"
            touch(o)
            _release_assignments(o["id"])
    p["status"] = "ABANDONED"
    touch(p)
    L.recompute_posture(p)
    L.recompute_claim_amounts(pid)
    return success_object(S.ser_project(p))


def _release_assignments(order_id):
    for a in db.assignments.values():
        if a["abatement_order_id"] == order_id and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)


# ===========================================================================
# Assessments
# ===========================================================================
@app.route("/api/assessments", methods=["POST"])
def create_assessment():
    auth_and_role({"ProjectManager", "LabTech"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "assessor_worker_id", "area_label"])
    # FK existence (priority 5)
    V.get_or_404("project", body["project_id"])
    V.get_or_404("worker", body["assessor_worker_id"])
    if not isinstance(body["area_label"], str) or not body["area_label"]:
        raise err("ERR_INVALID_REQUEST", "area_label must be a non-empty string")
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "assessor_worker_id": body["assessor_worker_id"],
        "area_label": body["area_label"],
        "finding_level": "CLEAN",
        "status": "DRAFT",
    })
    db.assessments[rec["id"]] = rec
    return success_object(S.ser_assessment(rec), 201)


@app.route("/api/assessments", methods=["GET"])
def list_assessments():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.assessments.values()),
                         [("project_id", "project_id"), ("assessor_worker_id", "assessor_worker_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_assessment(r) for r in page], limit, offset, total)


@app.route("/api/assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("assessment", aid)
    return success_object(S.ser_assessment(rec))


# ===========================================================================
# Samples
# ===========================================================================
@app.route("/api/samples", methods=["POST"])
def create_sample():
    auth_and_role({"LabTech"})
    body = V.get_body()
    V.require_fields(body, ["assessment_id", "project_id", "sample_type", "collected_at"])
    # FK existence (priority 5)
    assessment = V.get_or_404("assessment", body["assessment_id"])
    project = V.get_or_404("project", body["project_id"])
    # cross-project (priority 6): assessment must belong to project_id
    if assessment["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "assessment does not belong to project")
    # well-formedness (priority 7)
    stype = V.valid_enum(body, "sample_type", {"AIR", "SURFACE"})
    vol = None
    if stype == "AIR":
        if "volume_liters" not in body or body["volume_liters"] is None:
            raise err("ERR_INVALID_REQUEST", "AIR sample requires volume_liters")
        vol = V.positive_number(body, "volume_liters")
    else:  # SURFACE
        if "volume_liters" in body and body["volume_liters"] is not None:
            raise err("ERR_INVALID_REQUEST", "SURFACE sample must not supply volume_liters")
    collected = V.parse_required_dt(body, "collected_at")
    # temporal (priority 8)
    V.not_future(collected, "collected_at")

    rec = base_fields()
    rec.update({
        "assessment_id": body["assessment_id"],
        "project_id": body["project_id"],
        "sample_type": stype,
        "collected_at": body["collected_at"],
        "volume_liters": vol,
        "raw_count": None,
        "concentration": None,
        "result_grade": None,
        "status": "PENDING",
    })
    db.samples[rec["id"]] = rec
    # System transition: first sample under DRAFT assessment -> SAMPLED
    if assessment["status"] == "DRAFT":
        assessment["status"] = "SAMPLED"
        touch(assessment)
    return success_object(S.ser_sample(rec), 201)


@app.route("/api/samples", methods=["GET"])
def list_samples():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.samples.values()),
                         [("assessment_id", "assessment_id"), ("project_id", "project_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_sample(r) for r in page], limit, offset, total)


@app.route("/api/samples/<sid>", methods=["GET"])
def get_sample(sid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("sample", sid)
    return success_object(S.ser_sample(rec))


@app.route("/api/samples/<sid>/result", methods=["POST"])
def sample_result(sid):
    auth_and_role({"LabTech"})
    s = V.get_or_404("sample", sid)
    body = V.get_body()
    if s["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Sample is not PENDING")
    raw = body.get("raw_count")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise err("ERR_INVALID_REQUEST", "raw_count must be a non-negative integer")
    s["raw_count"] = raw
    s["concentration"] = L.compute_sample_concentration(s)
    s["result_grade"] = L.compute_sample_grade(s["concentration"], s["sample_type"])
    s["status"] = "ANALYZED"
    touch(s)
    # Cascade: assessment finding_level -> open_finding_count -> posture
    assessment = db.assessments.get(s["assessment_id"])
    if assessment is not None:
        L.maybe_advance_assessment_status(assessment)
        L.recompute_finding_level(assessment)
        project = db.projects.get(assessment["project_id"])
        if project is not None:
            L.recompute_open_finding_count(project)
            L.recompute_posture(project)
    return success_object(S.ser_sample(s))


@app.route("/api/samples/<sid>/void", methods=["POST"])
def sample_void(sid):
    auth_and_role({"ProjectManager"})
    s = V.get_or_404("sample", sid)
    if s["status"] not in ("PENDING", "ANALYZED"):
        raise err("ERR_INVALID_STATE", "Sample cannot be voided from its current state")
    assessment = db.assessments.get(s["assessment_id"])
    if s["status"] == "ANALYZED":
        # extra precondition: parent assessment not CLEARED
        if assessment is not None and assessment["status"] == "CLEARED":
            raise err("ERR_ASSESSMENT_ALREADY_CLEARED", "Parent assessment is already CLEARED")
        was_analyzed = True
    else:
        was_analyzed = False
    s["status"] = "VOIDED"
    touch(s)
    # Cascade: finding_level -> (if analyzed) open_finding_count -> posture
    if assessment is not None:
        L.recompute_finding_level(assessment)
        if was_analyzed:
            project = db.projects.get(assessment["project_id"])
            if project is not None:
                L.recompute_open_finding_count(project)
                L.recompute_posture(project)
    return success_object(S.ser_sample(s))


# ===========================================================================
# Containment Zones
# ===========================================================================
@app.route("/api/containment-zones", methods=["POST"])
def create_zone():
    auth_and_role({"ProjectManager", "AbatementSupervisor"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "zone_label", "required_pressure_pa"])
    V.get_or_404("project", body["project_id"])
    if not isinstance(body["zone_label"], str) or not body["zone_label"]:
        raise err("ERR_INVALID_REQUEST", "zone_label must be a non-empty string")
    rp = body["required_pressure_pa"]
    if not isinstance(rp, (int, float)) or isinstance(rp, bool):
        raise err("ERR_INVALID_REQUEST", "required_pressure_pa must be a number")
    if rp < L.MIN_NEGATIVE_PRESSURE_PA:
        raise err("ERR_INVALID_REQUEST", "required_pressure_pa must be >= %d" % L.MIN_NEGATIVE_PRESSURE_PA)
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "zone_label": body["zone_label"],
        "required_pressure_pa": rp,
        "latest_pressure_pa": 0,
        "is_compliant": False,
        "status": "SETUP",
    })
    db.zones[rec["id"]] = rec
    return success_object(S.ser_zone(rec), 201)


@app.route("/api/containment-zones", methods=["GET"])
def list_zones():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.zones.values()), [("project_id", "project_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_zone(r) for r in page], limit, offset, total)


@app.route("/api/containment-zones/<zid>", methods=["GET"])
def get_zone(zid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("zone", zid)
    return success_object(S.ser_zone(rec))


@app.route("/api/containment-zones/<zid>/pressure-logs", methods=["POST"])
def create_pressure_log(zid):
    auth_and_role({"AbatementSupervisor"})
    zone = V.get_or_404("zone", zid)
    body = V.get_body()
    V.require_fields(body, ["reading_pa", "reading_at"])
    rp = body["reading_pa"]
    if not isinstance(rp, (int, float)) or isinstance(rp, bool) or rp <= 0:
        raise err("ERR_INVALID_REQUEST", "reading_pa must be a positive number")
    reading_at = V.parse_required_dt(body, "reading_at")
    V.not_future(reading_at, "reading_at")
    # append-only event: only id + created_at (no version / updated_at)
    pl = base_fields(versioned=False)
    pl.update({
        "zone_id": zid,
        "reading_pa": rp,
        "reading_at": body["reading_at"],
    })
    db.pressure_logs[pl["id"]] = pl
    # recompute compliance; may flip ACTIVE<->BREACHED; recompute posture
    compliant = L.recompute_zone_compliance(zone)
    if zone["status"] == "ACTIVE" and not compliant:
        zone["status"] = "BREACHED"
        touch(zone)
    elif zone["status"] == "BREACHED" and compliant:
        zone["status"] = "ACTIVE"
        touch(zone)
    project = db.projects.get(zone["project_id"])
    if project is not None:
        L.recompute_posture(project)
    return success_object(S.ser_pressure_log(pl), 201)


@app.route("/api/pressure-logs", methods=["GET"])
def list_pressure_logs():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.pressure_logs.values()), [("zone_id", "zone_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_pressure_log(r) for r in page], limit, offset, total)


@app.route("/api/pressure-logs/<plid>", methods=["GET"])
def get_pressure_log(plid):
    auth_and_role(ALL_ROLES)
    rec = db.pressure_logs.get(plid)
    if rec is None:
        raise err("ERR_ZONE_NOT_FOUND", "Pressure log not found")
    return success_object(S.ser_pressure_log(rec))


@app.route("/api/containment-zones/<zid>/activate", methods=["POST"])
def activate_zone(zid):
    auth_and_role({"ProjectManager"})
    zone = V.get_or_404("zone", zid)
    if zone["status"] != "SETUP":
        raise err("ERR_INVALID_STATE", "Zone is not in SETUP")
    L.recompute_zone_compliance(zone)
    if not zone["is_compliant"]:
        raise err("ERR_CONTAINMENT_NOT_COMPLIANT", "Zone is not compliant")
    zone["status"] = "ACTIVE"
    touch(zone)
    project = db.projects.get(zone["project_id"])
    if project is not None:
        L.recompute_posture(project)
    return success_object(S.ser_zone(zone))


@app.route("/api/containment-zones/<zid>/dismantle", methods=["POST"])
def dismantle_zone(zid):
    auth_and_role({"ProjectManager"})
    zone = V.get_or_404("zone", zid)
    if zone["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Zone is not ACTIVE")
    orders = [o for o in db.orders.values() if o["zone_id"] == zid]
    if any(o["status"] in ("PLANNED", "IN_PROGRESS", "REOPENED") for o in orders):
        raise err("ERR_ABATEMENT_IN_PROGRESS", "An abatement order is active in this zone")
    signed = any(
        c["status"] == "SIGNED_OFF" for c in db.clearances.values() if c["zone_id"] == zid
    )
    if not signed:
        raise err("ERR_NO_PASSING_CLEARANCE", "No SIGNED_OFF clearance for this zone")
    zone["status"] = "DISMANTLED"
    touch(zone)
    project = db.projects.get(zone["project_id"])
    if project is not None:
        L.recompute_posture(project)
    return success_object(S.ser_zone(zone))


# ===========================================================================
# Abatement Orders
# ===========================================================================
@app.route("/api/abatement-orders", methods=["POST"])
def create_order():
    auth_and_role({"AbatementSupervisor"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "zone_id", "lead_worker_id", "abatement_type", "planned_weight_kg"])
    project = V.get_or_404("project", body["project_id"])
    zone = V.get_or_404("zone", body["zone_id"])
    worker = V.get_or_404("worker", body["lead_worker_id"])
    supersedes = body.get("supersedes_order_id")
    pred = None
    if supersedes is not None:
        pred = V.get_or_404("order", supersedes)
    # cross-project (priority 6)
    if zone["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "zone does not belong to project")
    if pred is not None and pred["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "superseded order does not belong to project")
    # well-formedness (priority 7)
    V.valid_enum(body, "abatement_type", {"ASBESTOS", "LEAD", "MOLD"})
    pw = V.positive_number(body, "planned_weight_kg")
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "zone_id": body["zone_id"],
        "lead_worker_id": body["lead_worker_id"],
        "abatement_type": body["abatement_type"],
        "planned_weight_kg": pw,
        "removed_weight_kg": None,
        "supersedes_order_id": supersedes,
        "revision_index": L.compute_revision_index(supersedes),
        "status": "PLANNED",
    })
    db.orders[rec["id"]] = rec
    L.recompute_posture(project)
    L.recompute_claim_amounts(project["id"])
    return success_object(S.ser_order(rec), 201)


@app.route("/api/abatement-orders", methods=["GET"])
def list_orders():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.orders.values()),
                         [("project_id", "project_id"), ("zone_id", "zone_id"),
                          ("lead_worker_id", "lead_worker_id"), ("supersedes_order_id", "supersedes_order_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_order(r) for r in page], limit, offset, total)


@app.route("/api/abatement-orders/<aid>", methods=["GET"])
def get_order(aid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("order", aid)
    return success_object(S.ser_order(rec))


@app.route("/api/abatement-orders/<aid>/start", methods=["POST"])
def start_order(aid):
    auth_and_role({"AbatementSupervisor"})
    o = V.get_or_404("order", aid)
    # state guard (priority 10)
    if o["status"] not in ("PLANNED", "REOPENED"):
        raise err("ERR_INVALID_STATE", "Order is not PLANNED or REOPENED")
    was_planned = o["status"] == "PLANNED"
    zone = db.zones.get(o["zone_id"])
    project = db.projects.get(o["project_id"])
    # zone active (priority 13)
    if zone is None or zone["status"] != "ACTIVE":
        raise err("ERR_ZONE_NOT_ACTIVE", "Referenced zone is not ACTIVE")
    # lead cert (priority 14)
    lead = db.workers.get(o["lead_worker_id"])
    if lead is None or not L.is_cert_current(lead) or lead["cert_type"] != o["abatement_type"]:
        raise err("ERR_WORKER_NOT_CERTIFIED", "Lead worker not certified for this abatement")
    # NESHAP gate (priority 16) — only on start from PLANNED when neshap_required
    if was_planned and project is not None and project.get("neshap_required"):
        if not _neshap_satisfied(project["id"]):
            raise err("ERR_NESHAP_NOTICE_NOT_MET", "NESHAP notification requirement not met")
    # certified crew (priority 18)
    if not _has_certified_crew(aid):
        raise err("ERR_NO_CERTIFIED_CREW", "No ACTIVE certified crew on this order")
    o["status"] = "IN_PROGRESS"
    touch(o)
    if project is not None:
        L.recompute_posture(project)
    return success_object(S.ser_order(o))


def _neshap_satisfied(project_id):
    now = clock.get()
    for p in db.permits.values():
        if p["project_id"] != project_id:
            continue
        if p["permit_type"] != "NESHAP_NOTIFICATION":
            continue
        if p["status"] != "ACKNOWLEDGED":
            continue
        if p.get("notice_days", 0) < L.NESHAP_NOTICE_DAYS:
            continue
        ws = parse_dt(p.get("work_start_at"))
        if ws is None or ws > now:
            continue
        return True
    return False


def _has_certified_crew(order_id):
    for a in db.assignments.values():
        if a["abatement_order_id"] == order_id and a["status"] == "ACTIVE":
            w = db.workers.get(a["worker_id"])
            if w is not None and L.is_cert_current(w):
                return True
    return False


@app.route("/api/abatement-orders/<aid>/complete", methods=["POST"])
def complete_order(aid):
    auth_and_role({"AbatementSupervisor"})
    o = V.get_or_404("order", aid)
    body = V.get_body()
    # state guard (priority 10) — must precede zone-not-active (priority 13)
    if o["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Order is not IN_PROGRESS")
    # removed_weight_kg well-formedness (priority 7-equivalent business rule)
    rw = body.get("removed_weight_kg")
    if not isinstance(rw, (int, float)) or isinstance(rw, bool) or rw <= 0:
        raise err("ERR_INVALID_REQUEST", "removed_weight_kg must be a positive number")
    zone = db.zones.get(o["zone_id"])
    if zone is None or zone["status"] != "ACTIVE":
        raise err("ERR_ZONE_NOT_ACTIVE", "Referenced zone is not ACTIVE")
    # accepted manifest covering removed weight (priority 19)
    covering = [
        m for m in db.manifests.values()
        if m["abatement_order_id"] == aid and m["status"] == "ACCEPTED"
        and m["manifest_weight_kg"] >= rw
    ]
    if not covering:
        raise err("ERR_MANIFEST_WEIGHT_SHORT", "No ACCEPTED manifest covers the removed weight")
    o["removed_weight_kg"] = rw
    o["status"] = "COMPLETED"
    touch(o)
    project = db.projects.get(o["project_id"])
    if project is not None:
        L.recompute_claim_amounts(project["id"])
        L.recompute_posture(project)
    return success_object(S.ser_order(o))


@app.route("/api/abatement-orders/<aid>/cancel", methods=["POST"])
def cancel_order(aid):
    auth_and_role({"ProjectManager"})
    o = V.get_or_404("order", aid)
    if o["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    if o["status"] == "IN_PROGRESS":
        # no in-flight clearance (priority 21)
        inflight = [
            c for c in db.clearances.values()
            if c["abatement_order_id"] == aid and c["status"] in ("ANALYZED", "PASSED", "SIGNED_OFF")
        ]
        if inflight:
            raise err("ERR_CLEARANCE_IN_PROGRESS", "An in-flight clearance test references this order")
    o["status"] = "CANCELLED"
    touch(o)
    _release_assignments(aid)
    project = db.projects.get(o["project_id"])
    if project is not None:
        L.recompute_claim_amounts(project["id"])
        L.recompute_posture(project)
    return success_object(S.ser_order(o))


# ===========================================================================
# Worker Assignments
# ===========================================================================
@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    auth_and_role({"AbatementSupervisor"})
    body = V.get_body()
    V.require_fields(body, ["abatement_order_id", "worker_id", "shift_start_at", "shift_end_at"])
    V.get_or_404("order", body["abatement_order_id"])
    V.get_or_404("worker", body["worker_id"])
    start = V.parse_required_dt(body, "shift_start_at")
    end = V.parse_required_dt(body, "shift_end_at")
    if not (end > start):
        raise err("ERR_INVALID_REQUEST", "shift_end_at must be after shift_start_at")
    rec = base_fields()
    rec.update({
        "abatement_order_id": body["abatement_order_id"],
        "worker_id": body["worker_id"],
        "shift_start_at": body["shift_start_at"],
        "shift_end_at": body["shift_end_at"],
        "status": "ACTIVE",
    })
    db.assignments[rec["id"]] = rec
    return success_object(S.ser_assignment(rec), 201)


@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.assignments.values()),
                         [("abatement_order_id", "abatement_order_id"), ("worker_id", "worker_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_assignment(r) for r in page], limit, offset, total)


@app.route("/api/assignments/<asid>", methods=["GET"])
def get_assignment(asid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("assignment", asid)
    return success_object(S.ser_assignment(rec))


# ===========================================================================
# Disposal Manifests
# ===========================================================================
@app.route("/api/disposal-manifests", methods=["POST"])
def create_manifest():
    auth_and_role({"AbatementSupervisor"})
    body = V.get_body()
    V.require_fields(body, ["abatement_order_id", "project_id", "hauler_name", "manifest_weight_kg"])
    order = V.get_or_404("order", body["abatement_order_id"])
    project = V.get_or_404("project", body["project_id"])
    if order["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "order does not belong to project")
    if not isinstance(body["hauler_name"], str) or not body["hauler_name"]:
        raise err("ERR_INVALID_REQUEST", "hauler_name must be a non-empty string")
    mw = V.positive_number(body, "manifest_weight_kg")
    rec = base_fields()
    rec.update({
        "abatement_order_id": body["abatement_order_id"],
        "project_id": body["project_id"],
        "hauler_name": body["hauler_name"],
        "manifest_weight_kg": mw,
        "disposal_fee_cents": L.compute_disposal_fee(mw, order["abatement_type"]),
        "status": "DRAFT",
    })
    db.manifests[rec["id"]] = rec
    L.recompute_claim_amounts(project["id"])
    return success_object(S.ser_manifest(rec), 201)


@app.route("/api/disposal-manifests", methods=["GET"])
def list_manifests():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.manifests.values()),
                         [("abatement_order_id", "abatement_order_id"), ("project_id", "project_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_manifest(r) for r in page], limit, offset, total)


@app.route("/api/disposal-manifests/<mid>", methods=["GET"])
def get_manifest(mid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("manifest", mid)
    return success_object(S.ser_manifest(rec))


@app.route("/api/disposal-manifests/<mid>/submit", methods=["POST"])
def submit_manifest(mid):
    auth_and_role({"AbatementSupervisor"})
    m = V.get_or_404("manifest", mid)
    if m["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Manifest is not DRAFT")
    order = db.orders.get(m["abatement_order_id"])
    if order is None or order["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "Parent order must be IN_PROGRESS or COMPLETED")
    if order["abatement_type"] == "ASBESTOS":
        has_transport = any(
            p["project_id"] == m["project_id"] and p["permit_type"] == "TRANSPORT"
            and p["status"] == "ACKNOWLEDGED"
            for p in db.permits.values()
        )
        if not has_transport:
            raise err("ERR_TRANSPORT_PERMIT_MISSING", "No ACKNOWLEDGED TRANSPORT permit")
    m["status"] = "SUBMITTED"
    touch(m)
    return success_object(S.ser_manifest(m))


@app.route("/api/disposal-manifests/<mid>/accept", methods=["POST"])
def accept_manifest(mid):
    auth_and_role({"ProjectManager"})
    m = V.get_or_404("manifest", mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Manifest is not SUBMITTED")
    order = db.orders.get(m["abatement_order_id"])
    # finalize fee
    if order is not None:
        m["disposal_fee_cents"] = L.compute_disposal_fee(m["manifest_weight_kg"], order["abatement_type"])
    m["status"] = "ACCEPTED"
    touch(m)
    L.recompute_claim_amounts(m["project_id"])
    return success_object(S.ser_manifest(m))


@app.route("/api/disposal-manifests/<mid>/void", methods=["POST"])
def void_manifest(mid):
    auth_and_role({"ProjectManager"})
    m = V.get_or_404("manifest", mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED manifest can be voided manually")
    m["status"] = "VOIDED"
    touch(m)
    L.recompute_claim_amounts(m["project_id"], recompute_settled=False)
    return success_object(S.ser_manifest(m))


# ===========================================================================
# Clearance Tests
# ===========================================================================
@app.route("/api/clearance-tests", methods=["POST"])
def create_clearance():
    auth_and_role({"LabTech"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "zone_id", "abatement_order_id",
                            "sampler_worker_id", "clearance_air_count", "clearance_volume_liters"])
    project = V.get_or_404("project", body["project_id"])
    zone = V.get_or_404("zone", body["zone_id"])
    order = V.get_or_404("order", body["abatement_order_id"])
    V.get_or_404("worker", body["sampler_worker_id"])
    # cross-project (priority 6)
    if zone["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "zone does not belong to project")
    if order["project_id"] != project["id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", "order does not belong to project")
    # well-formedness (priority 7)
    cac = body.get("clearance_air_count")
    if not isinstance(cac, int) or isinstance(cac, bool) or cac < 0:
        raise err("ERR_INVALID_REQUEST", "clearance_air_count must be a non-negative integer")
    cvl = V.positive_number(body, "clearance_volume_liters")
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "zone_id": body["zone_id"],
        "abatement_order_id": body["abatement_order_id"],
        "sampler_worker_id": body["sampler_worker_id"],
        "signoff_worker_id": None,
        "clearance_air_count": cac,
        "clearance_volume_liters": cvl,
        "clearance_concentration": None,
        "outcome": None,
        "status": "DRAFT",
    })
    db.clearances[rec["id"]] = rec
    return success_object(S.ser_clearance(rec), 201)


@app.route("/api/clearance-tests", methods=["GET"])
def list_clearances():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.clearances.values()),
                         [("project_id", "project_id"), ("zone_id", "zone_id"),
                          ("abatement_order_id", "abatement_order_id"),
                          ("sampler_worker_id", "sampler_worker_id"),
                          ("signoff_worker_id", "signoff_worker_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_clearance(r) for r in page], limit, offset, total)


@app.route("/api/clearance-tests/<cid>", methods=["GET"])
def get_clearance(cid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("clearance", cid)
    return success_object(S.ser_clearance(rec))


@app.route("/api/clearance-tests/<cid>/analyze", methods=["POST"])
def analyze_clearance(cid):
    auth_and_role({"LabTech"})
    c = V.get_or_404("clearance", cid)
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Clearance test is not DRAFT")
    order = db.orders.get(c["abatement_order_id"])
    if order is None or order["status"] != "COMPLETED":
        raise err("ERR_ORDER_NOT_COMPLETED", "Referenced order is not COMPLETED")
    project = db.projects.get(c["project_id"])
    c["clearance_concentration"] = L.compute_clearance_concentration(c)
    c["outcome"] = L.compute_clearance_outcome(c["clearance_concentration"], project["hazard_class"])
    if c["outcome"] == "PASS":
        c["status"] = "PASSED"
        touch(c)
    else:
        c["status"] = "FAILED"
        touch(c)
        # cascade: order COMPLETED -> REOPENED; void ACCEPTED/SUBMITTED manifests;
        # recompute settlement; recompute posture
        if order["status"] == "COMPLETED":
            order["status"] = "REOPENED"
            touch(order)
            for m in db.manifests.values():
                if m["abatement_order_id"] == order["id"] and m["status"] in ("ACCEPTED", "SUBMITTED"):
                    m["status"] = "VOIDED"
                    touch(m)
        if project is not None:
            L.recompute_claim_amounts(project["id"])
            L.recompute_posture(project)
    return success_object(S.ser_clearance(c))


@app.route("/api/clearance-tests/<cid>/signoff", methods=["POST"])
def signoff_clearance(cid):
    auth_and_role({"Hygienist"})
    c = V.get_or_404("clearance", cid)
    body = V.get_body()
    # required fields (well-formedness)
    if "signoff_worker_id" not in body or body["signoff_worker_id"] is None:
        raise err("ERR_INVALID_REQUEST", "signoff_worker_id is required")
    if "expected_project_version" not in body or body["expected_project_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_project_version is required")
    epv = body["expected_project_version"]
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be an integer")
    # FK existence of signoff worker
    worker = V.get_or_404("worker", body["signoff_worker_id"])
    project = db.projects.get(c["project_id"])
    # OCC (priority 9) BEFORE state guard per concurrency_rules / PRD §2.6,
    # but PRD §3.8/§2.7 lists state guard (priority 10) after OCC (priority 9).
    # Validation order (PRD §2.7): ... OCC (9) ... state (10).
    if project is None or epv != project["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match project version")
    # state guard (priority 10)
    if c["status"] != "PASSED":
        raise err("ERR_INVALID_STATE", "Clearance test is not PASSED")
    # hygienist cert (priority 14)
    if worker["cert_type"] != "HYGIENIST" or not L.is_cert_current(worker):
        raise err("ERR_WORKER_NOT_CERTIFIED", "Sign-off worker is not a current HYGIENIST")
    # independence (priority 15)
    order = db.orders.get(c["abatement_order_id"])
    lead_id = order["lead_worker_id"] if order else None
    if body["signoff_worker_id"] == c["sampler_worker_id"] or body["signoff_worker_id"] == lead_id:
        raise err("ERR_SIGNOFF_NOT_INDEPENDENT", "Sign-off worker is not independent")
    c["signoff_worker_id"] = body["signoff_worker_id"]
    c["status"] = "SIGNED_OFF"
    touch(c)
    # PRD §3.8: the sign-off cascade — clearing assessments, recomputing
    # open_finding_count and posture — culminates in the project's version being
    # "incremented by one". The net effect of the whole cascade on the project is
    # exactly one version increment (that single, deterministic bump is what makes
    # a competing in-flight sign-off's expected_project_version stale). We pin the
    # base version before the cascade and force a net +1 afterward so that the
    # internal derived-field reconciliations (posture/finding-count) do not turn
    # the documented single increment into a multi-step jump.
    base_version = project["version"]
    # cascade: covered assessments ANALYZED -> CLEARED
    _clear_covered_assessments(c)
    L.recompute_open_finding_count(project)
    L.recompute_posture(project)
    # net single version bump for the operation (PRD §3.8)
    project["version"] = base_version + 1
    from util import now_iso
    project["updated_at"] = now_iso()
    return success_object(S.ser_clearance(c))


def _clear_covered_assessments(clearance):
    """Covered assessments: ANALYZED assessments under the same project whose
    zone is covered by an AbatementOrder.zone_id == clearance.zone_id.
    Assessments are not directly tied to a zone, so we clear ANALYZED assessments
    on the project that belong to the cleared zone via the order's zone."""
    project_id = clearance["project_id"]
    zone_id = clearance["zone_id"]
    # An assessment is covered if there is an AbatementOrder in the cleared zone
    # under the project (i.e. the clearance's order zone). Per PRD §3.8 the cleared
    # zone's assessments advance. Assessments carry no zone fk, so all ANALYZED
    # assessments under the project are covered when their zone is cleared.
    for a in L.project_assessments(project_id):
        if a["status"] == "ANALYZED":
            a["status"] = "CLEARED"
            touch(a)


# ===========================================================================
# Permits
# ===========================================================================
@app.route("/api/permits", methods=["POST"])
def create_permit():
    auth_and_role({"ComplianceOfficer"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "permit_type", "postmarked_at", "work_start_at"])
    V.get_or_404("project", body["project_id"])
    V.valid_enum(body, "permit_type", {"NESHAP_NOTIFICATION", "DEMOLITION", "TRANSPORT"})
    postmarked = V.parse_required_dt(body, "postmarked_at")
    work_start = V.parse_required_dt(body, "work_start_at")
    V.not_future(postmarked, "postmarked_at")
    notice_days = days_between_floor(postmarked, work_start, L.SECONDS_PER_DAY)
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "permit_type": body["permit_type"],
        "postmarked_at": body["postmarked_at"],
        "work_start_at": body["work_start_at"],
        "notice_days": notice_days,
        "status": "DRAFT",
    })
    db.permits[rec["id"]] = rec
    return success_object(S.ser_permit(rec), 201)


@app.route("/api/permits", methods=["GET"])
def list_permits():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.permits.values()),
                         [("project_id", "project_id"), ("permit_type", "permit_type")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_permit(r) for r in page], limit, offset, total)


@app.route("/api/permits/<pmid>", methods=["GET"])
def get_permit(pmid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("permit", pmid)
    return success_object(S.ser_permit(rec))


@app.route("/api/permits/<pmid>/submit", methods=["POST"])
def submit_permit(pmid):
    auth_and_role({"ComplianceOfficer"})
    p = V.get_or_404("permit", pmid)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Permit is not DRAFT")
    if p["permit_type"] == "NESHAP_NOTIFICATION" and p["notice_days"] < L.NESHAP_NOTICE_DAYS:
        raise err("ERR_NESHAP_NOTICE_NOT_MET", "NESHAP notice lead time too short")
    p["status"] = "SUBMITTED"
    touch(p)
    return success_object(S.ser_permit(p))


@app.route("/api/permits/<pmid>/acknowledge", methods=["POST"])
def acknowledge_permit(pmid):
    auth_and_role({"ComplianceOfficer"})
    p = V.get_or_404("permit", pmid)
    if p["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Permit is not SUBMITTED")
    p["status"] = "ACKNOWLEDGED"
    touch(p)
    return success_object(S.ser_permit(p))


@app.route("/api/permits/<pmid>/expire", methods=["POST"])
def expire_permit(pmid):
    auth_and_role({"ComplianceOfficer"})
    p = V.get_or_404("permit", pmid)
    if p["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Permit is not ACKNOWLEDGED")
    p["status"] = "EXPIRED"
    touch(p)
    return success_object(S.ser_permit(p))


# ===========================================================================
# Insurance Claims
# ===========================================================================
@app.route("/api/insurance-claims", methods=["POST"])
def create_claim():
    auth_and_role({"ProjectManager"})
    body = V.get_body()
    V.require_fields(body, ["project_id", "policy_number", "deductible_cents", "coverage_limit_cents"])
    V.get_or_404("project", body["project_id"])
    if not isinstance(body["policy_number"], str) or not body["policy_number"]:
        raise err("ERR_INVALID_REQUEST", "policy_number must be a non-empty string")
    ded = V.nonneg_int(body, "deductible_cents")
    cov = body.get("coverage_limit_cents")
    if not isinstance(cov, int) or isinstance(cov, bool) or cov <= 0:
        raise err("ERR_INVALID_REQUEST", "coverage_limit_cents must be a positive integer")
    rec = base_fields()
    rec.update({
        "project_id": body["project_id"],
        "policy_number": body["policy_number"],
        "deductible_cents": ded,
        "coverage_limit_cents": cov,
        "estimated_amount_cents": 0,
        "settled_amount_cents": 0,
        "status": "OPEN",
    })
    db.claims[rec["id"]] = rec
    # PRD: a new claim starts with both amounts zero. Per the scaffold corner
    # tests the values are only asserted after explicit submit/settle, so we
    # leave them zeroed at creation to match "starts OPEN with both zero".
    return success_object(S.ser_claim(rec), 201)


@app.route("/api/insurance-claims", methods=["GET"])
def list_claims():
    auth_and_role(ALL_ROLES)
    limit, offset = V.pagination()
    recs = filtered_list(list(db.claims.values()), [("project_id", "project_id")])
    recs = sorted_by_created(recs)
    page, total = V.paginate(recs, limit, offset)
    return success_array([S.ser_claim(r) for r in page], limit, offset, total)


@app.route("/api/insurance-claims/<clid>", methods=["GET"])
def get_claim(clid):
    auth_and_role(ALL_ROLES)
    rec = V.get_or_404("claim", clid)
    return success_object(S.ser_claim(rec))


@app.route("/api/insurance-claims/<clid>/submit", methods=["POST"])
def submit_claim(clid):
    auth_and_role({"ProjectManager"})
    c = V.get_or_404("claim", clid)
    if c["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Claim is not OPEN")
    project = db.projects.get(c["project_id"])
    if project is None or project["posture"] not in ("CLEARANCE_PENDING", "VERIFIED"):
        raise err("ERR_PROJECT_NOT_READY_FOR_BILLING", "Project posture not ready for billing")
    c["status"] = "SUBMITTED"
    # PRD §3.9: submission recomputes the estimate. We also reconcile the
    # settlement here so a claim opened after the order completed reflects the
    # current actuals (settled is a derived projection per PRD §2.5).
    c["estimated_amount_cents"] = L.compute_estimate(c["project_id"])
    c["settled_amount_cents"] = L.compute_settlement(c["project_id"], c)
    touch(c)
    return success_object(S.ser_claim(c))


@app.route("/api/insurance-claims/<clid>/settle", methods=["POST"])
def settle_claim(clid):
    auth_and_role({"ComplianceOfficer"})
    c = V.get_or_404("claim", clid)
    body = V.get_body()
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED")
    project = db.projects.get(c["project_id"])
    if project is None or project["posture"] != "VERIFIED":
        raise err("ERR_PROJECT_NOT_VERIFIED", "Project posture is not VERIFIED")
    gross = L.compute_settlement_gross(c["project_id"])
    allow_over_cap = bool(body.get("allow_over_cap", False))
    if gross > c["coverage_limit_cents"] and not allow_over_cap:
        raise err("ERR_COVERAGE_LIMIT_EXCEEDED", "Gross exceeds coverage limit; allow_over_cap required")
    c["status"] = "SETTLED"
    settled = L.compute_settlement(c["project_id"], c)
    c["settled_amount_cents"] = settled
    touch(c)
    return success_object(S.ser_claim(c))


@app.route("/api/insurance-claims/<clid>/deny", methods=["POST"])
def deny_claim(clid):
    auth_and_role({"ComplianceOfficer"})
    c = V.get_or_404("claim", clid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED")
    c["status"] = "DENIED"
    touch(c)
    return success_object(S.ser_claim(c))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
