"""Routes: org units, logical clock, employees, coaching log, performance
concerns, PIP templates, rating cycles."""

from flask import Blueprint, request

from core import (
    db, auth, require_role, ok_object, list_response, body, require_field,
    min_len, enum_field, new_record, new_append_record, touch, public,
    parse_dt, fmt_like, days, ALL_ROLES,
    E_FORBIDDEN, E_NOT_FOUND, E_PARENT_MISMATCH, E_INVALID_STATE, E_SOD,
    E_EMPLOYEE_NOT_ACTIVE, E_INVALID_REQUEST, E_COACHING_MISMATCH,
    E_COACHING_NOT_FORMAL, E_INSUFFICIENT_COACHING, E_TEMPLATE_WEIGHT_SUM,
    E_TEMPLATE_CADENCE, E_TEMPLATE_IN_USE, E_CYCLE_STILL_OPEN,
    E_CYCLE_TOO_RECENT, err,
)
from business import run_clock_sweeps

bp = Blueprint("core_routes", __name__)

JOB_FAMILIES = {"ENGINEERING", "SALES", "OPERATIONS", "SUPPORT", "FINANCE"}
COACH_CATEGORIES = {"QUALITY", "VELOCITY", "ATTENDANCE", "CONDUCT", "COLLABORATION"}
COACH_SEVERITIES = {"INFORMAL", "DOCUMENTED", "ESCALATED"}
CYCLE_STATUSES = {"OPEN", "CALIBRATION", "PUBLISHED", "ARCHIVED"}

READERS = ALL_ROLES


# ---------------------------------------------------------------------------
# Shared resolvers (existence left-to-right, then parent ownership)
# ---------------------------------------------------------------------------

def resolve_ou(ou_id):
    ou = db.org_units.get(ou_id)
    if ou is None:
        err(E_NOT_FOUND, "org unit not found")
    return ou


def resolve_employee(ou_id, emp_id):
    ou = resolve_ou(ou_id)
    emp = db.employees.get(emp_id)
    if emp is None:
        err(E_NOT_FOUND, "employee not found")
    if emp["hr_org_unit_id"] != ou["id"]:
        err(E_PARENT_MISMATCH, "employee does not belong to org unit")
    return ou, emp


def resolve_template(ou_id, template_id):
    ou = resolve_ou(ou_id)
    t = db.templates.get(template_id)
    if t is None:
        err(E_NOT_FOUND, "template not found")
    if t["hr_org_unit_id"] != ou["id"]:
        err(E_PARENT_MISMATCH, "template does not belong to org unit")
    return ou, t


def resolve_cycle(ou_id, cycle_id):
    ou = resolve_ou(ou_id)
    c = db.cycles.get(cycle_id)
    if c is None:
        err(E_NOT_FOUND, "rating cycle not found")
    if c["hr_org_unit_id"] != ou["id"]:
        err(E_PARENT_MISMATCH, "rating cycle does not belong to org unit")
    return ou, c


def resolve_concern(ou_id, emp_id, concern_id):
    ou, emp = resolve_employee(ou_id, emp_id)
    c = db.concerns.get(concern_id)
    if c is None:
        err(E_NOT_FOUND, "performance concern not found")
    if c["employee_id"] != emp["id"]:
        err(E_PARENT_MISMATCH, "concern does not belong to employee")
    return ou, emp, c


# ---------------------------------------------------------------------------
# Org units & clock
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units")
def create_org_unit():
    uid, role = auth()
    require_role(role, ["HRSystemAdmin"])
    b = body()
    name = require_field(b, "name")
    if not isinstance(name, str) or not name.strip():
        err(E_INVALID_REQUEST, "name must be a non-empty string")
    rec = new_record()
    rec.update({
        "name": name,
        "current_utc": "2026-08-01T00:00:00Z",
        "pip_policy_version": 1,
    })
    db.org_units[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>")
def get_org_unit(ouId):
    uid, role = auth()
    require_role(role, READERS)
    ou = resolve_ou(ouId)
    return ok_object(public(ou))


@bp.post("/hr-org-units/<ouId>/_clock/set_current_utc")
def set_clock(ouId):
    uid, role = auth()
    require_role(role, ["HRSystemAdmin"])
    ou = resolve_ou(ouId)
    b = body()
    to_iso8601 = require_field(b, "to_iso8601")
    target = parse_dt(to_iso8601)
    if target is None:
        err(E_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp")
    current = parse_dt(ou["current_utc"])
    if target < current:
        err(E_INVALID_REQUEST, "to_iso8601 must be monotonically non-decreasing")
    ou["current_utc"] = fmt_like(target, to_iso8601)
    touch(ou)
    run_clock_sweeps(ou)
    return ok_object(public(ou))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees")
def create_employee(ouId):
    uid, role = auth()
    require_role(role, ["HRSystemAdmin"])
    ou = resolve_ou(ouId)
    b = body()
    full_name = require_field(b, "full_name")
    email = require_field(b, "email")
    job_family = enum_field(require_field(b, "job_family"), JOB_FAMILIES, "job_family")
    job_level = require_field(b, "job_level")
    if isinstance(job_level, bool) or not isinstance(job_level, int) \
            or job_level < 1 or job_level > 10:
        err(E_INVALID_REQUEST, "job_level must be an integer between 1 and 10")
    manager_id = b.get("manager_id")
    if manager_id is not None and not isinstance(manager_id, str):
        err(E_INVALID_REQUEST, "manager_id must be a string")
    rec = new_record()
    rec.update({
        "hr_org_unit_id": ou["id"],
        "full_name": full_name,
        "email": email,
        "job_family": job_family,
        "job_level": job_level,
        "manager_id": manager_id,
        "employment_status": "ACTIVE",
        "active_pip_id": None,
        "terminated_at": None,
    })
    db.employees[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>")
def get_employee(ouId, empId):
    uid, role = auth()
    require_role(role, READERS)
    ou, emp = resolve_employee(ouId, empId)
    return ok_object(public(emp))


@bp.get("/hr-org-units/<ouId>/employees")
def list_employees(ouId):
    uid, role = auth()
    require_role(role, READERS)
    ou = resolve_ou(ouId)
    filters = {
        "job_family": request.args.get("job_family"),
        "job_level": request.args.get("job_level"),
        "employment_status": request.args.get("employment_status"),
        "manager_id": request.args.get("manager_id"),
    }
    records = [e for e in db.employees.values() if e["hr_org_unit_id"] == ou["id"]]
    return list_response(records, filters)


# ---------------------------------------------------------------------------
# Coaching log
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/coaching-log-entries")
def create_coaching_entry(ouId, empId):
    uid, role = auth()
    require_role(role, ["Manager"])
    ou, emp = resolve_employee(ouId, empId)
    b = body()
    occurred_raw = require_field(b, "occurred_at")
    occurred = parse_dt(occurred_raw)
    if occurred is None:
        err(E_INVALID_REQUEST, "occurred_at must be an ISO 8601 timestamp")
    category = enum_field(require_field(b, "category"), COACH_CATEGORIES, "category")
    severity = enum_field(require_field(b, "severity"), COACH_SEVERITIES, "severity")
    narrative = min_len(require_field(b, "narrative"), 40, "narrative")
    if emp.get("manager_id") != uid:
        err(E_FORBIDDEN, "acting user must be the employee's direct manager")
    rec = new_append_record()
    rec.update({
        "employee_id": emp["id"],
        "author_manager_id": uid,
        "occurred_at": fmt_like(occurred, occurred_raw),
        "category": category,
        "severity": severity,
        "narrative": narrative,
        "concern_id": None,
    })
    db.coaching_entries[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/coaching-log-entries")
def list_coaching_entries(ouId, empId):
    uid, role = auth()
    require_role(role, ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
                        "LegalCounsel", "Manager"])
    ou, emp = resolve_employee(ouId, empId)
    filters = {
        "category": request.args.get("category"),
        "severity": request.args.get("severity"),
        "concern_id": request.args.get("concern_id"),
    }
    records = [c for c in db.coaching_entries.values() if c["employee_id"] == emp["id"]]
    return list_response(records, filters)


# ---------------------------------------------------------------------------
# Performance concerns
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/performance-concerns")
def create_concern(ouId, empId):
    uid, role = auth()
    require_role(role, ["Manager"])
    ou, emp = resolve_employee(ouId, empId)
    b = body()
    category = enum_field(require_field(b, "category"), COACH_CATEGORIES, "category")
    summary = min_len(require_field(b, "summary"), 20, "summary")
    entry_ids = require_field(b, "coaching_log_entry_ids")
    if not isinstance(entry_ids, list) or not all(isinstance(x, str) for x in entry_ids):
        err(E_INVALID_REQUEST, "coaching_log_entry_ids must be an array of strings")
    if emp.get("manager_id") != uid:
        err(E_FORBIDDEN, "acting user must be the employee's direct manager")
    rec = new_record()
    rec.update({
        "employee_id": emp["id"],
        "raised_by_manager_id": uid,
        "category": category,
        "summary": summary,
        "coaching_log_entry_ids": list(entry_ids),
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "decided_by_hrbp_id": None,
    })
    db.concerns[rec["id"]] = rec
    # Link referenced entries back to this concern
    for eid in entry_ids:
        entry = db.coaching_entries.get(eid)
        if entry is not None:
            entry["concern_id"] = rec["id"]
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/performance-concerns")
def list_concerns(ouId, empId):
    uid, role = auth()
    require_role(role, ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
                        "LegalCounsel", "Manager"])
    ou, emp = resolve_employee(ouId, empId)
    filters = {
        "status": request.args.get("status"),
        "category": request.args.get("category"),
    }
    records = [c for c in db.concerns.values() if c["employee_id"] == emp["id"]]
    return list_response(records, filters)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/performance-concerns/<concernId>")
def get_concern(ouId, empId, concernId):
    uid, role = auth()
    require_role(role, ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
                        "LegalCounsel", "Manager"])
    ou, emp, concern = resolve_concern(ouId, empId, concernId)
    return ok_object(public(concern))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/performance-concerns/<concernId>/submit")
def submit_concern(ouId, empId, concernId):
    uid, role = auth()
    require_role(role, ["Manager"])
    ou, emp, concern = resolve_concern(ouId, empId, concernId)
    if concern["status"] != "DRAFT":
        err(E_INVALID_STATE, "concern is not DRAFT")
    if concern["raised_by_manager_id"] != uid:
        err(E_FORBIDDEN, "only the concern's author may submit it")
    entry_ids = concern["coaching_log_entry_ids"]
    if len(entry_ids) < 2:
        err(E_INSUFFICIENT_COACHING, "at least two coaching entries are required")
    for eid in entry_ids:
        entry = db.coaching_entries.get(eid)
        if entry is None or entry["employee_id"] != concern["employee_id"]:
            err(E_COACHING_MISMATCH, "coaching entry does not belong to this employee")
    for eid in entry_ids:
        entry = db.coaching_entries[eid]
        if entry["severity"] not in ("DOCUMENTED", "ESCALATED"):
            err(E_COACHING_NOT_FORMAL, "coaching entry is not DOCUMENTED or ESCALATED")
    concern["status"] = "SUBMITTED"
    concern["submitted_at"] = ou["current_utc"]
    touch(concern)
    return ok_object(public(concern))


def _decide_concern(ouId, empId, concernId, action):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, concern = resolve_concern(ouId, empId, concernId)
    if concern["status"] != "SUBMITTED":
        err(E_INVALID_STATE, "concern is not SUBMITTED")
    if concern["raised_by_manager_id"] == uid:
        err(E_SOD, "the HRBP deciding a concern must not be the manager who raised it")
    if action == "accept":
        if emp["employment_status"] != "ACTIVE":
            err(E_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
        concern["status"] = "ACCEPTED"
        concern["decided_at"] = ou["current_utc"]
        concern["decided_by_hrbp_id"] = uid
        touch(concern)
        for eid in concern["coaching_log_entry_ids"]:
            entry = db.coaching_entries.get(eid)
            if entry is not None:
                entry["severity"] = "ESCALATED"
    else:
        concern["status"] = "REJECTED_INSUFFICIENT"
        concern["decided_at"] = ou["current_utc"]
        concern["decided_by_hrbp_id"] = uid
        touch(concern)
    return ok_object(public(concern))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/performance-concerns/<concernId>/accept")
def accept_concern(ouId, empId, concernId):
    return _decide_concern(ouId, empId, concernId, "accept")


@bp.post("/hr-org-units/<ouId>/employees/<empId>/performance-concerns/<concernId>/reject")
def reject_concern(ouId, empId, concernId):
    return _decide_concern(ouId, empId, concernId, "reject")


# ---------------------------------------------------------------------------
# PIP templates
# ---------------------------------------------------------------------------

def _validate_blueprints(blueprints):
    """Returns (ok, weight_sum_ok). Raises ERR_INVALID_REQUEST on shape errors."""
    if not isinstance(blueprints, list) or not (1 <= len(blueprints) <= 5):
        err(E_INVALID_REQUEST, "goal_blueprints must contain 1..5 entries")
    for bp_i in blueprints:
        if not isinstance(bp_i, dict):
            err(E_INVALID_REQUEST, "each goal blueprint must be an object")
        for f in ("metric_key", "target_value", "unit", "weight"):
            if f not in bp_i or bp_i[f] is None:
                err(E_INVALID_REQUEST, "blueprint is missing field '%s'" % f)
        if not isinstance(bp_i["metric_key"], str) or not bp_i["metric_key"]:
            err(E_INVALID_REQUEST, "metric_key must be a non-empty string")
        if isinstance(bp_i["target_value"], bool) or \
                not isinstance(bp_i["target_value"], (int, float)):
            err(E_INVALID_REQUEST, "target_value must be a number")
        if not isinstance(bp_i["unit"], str):
            err(E_INVALID_REQUEST, "unit must be a string")
        if isinstance(bp_i["weight"], bool) or not isinstance(bp_i["weight"], int) \
                or not (1 <= bp_i["weight"] <= 100):
            err(E_INVALID_REQUEST, "weight must be an integer between 1 and 100")


def _template_geometry_ok(t):
    weights_ok = sum(bp["weight"] for bp in t["goal_blueprints"]) == 100
    duration_ok = 30 <= t["duration_days"] <= 180
    cadence_ok = 7 <= t["check_in_cadence_days"] <= 30
    weight_and_range_ok = weights_ok and duration_ok and cadence_ok
    divides_ok = cadence_ok and duration_ok and \
        (t["duration_days"] % t["check_in_cadence_days"] == 0)
    return weight_and_range_ok, divides_ok


@bp.post("/hr-org-units/<ouId>/pip-templates")
def create_template(ouId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou = resolve_ou(ouId)
    b = body()
    name = require_field(b, "name")
    category = enum_field(require_field(b, "category"), COACH_CATEGORIES, "category")
    blueprints = require_field(b, "goal_blueprints")
    _validate_blueprints(blueprints)
    duration_days = require_field(b, "duration_days")
    if isinstance(duration_days, bool) or not isinstance(duration_days, int):
        err(E_INVALID_REQUEST, "duration_days must be an integer")
    cadence = require_field(b, "check_in_cadence_days")
    if isinstance(cadence, bool) or not isinstance(cadence, int):
        err(E_INVALID_REQUEST, "check_in_cadence_days must be an integer")
    rec = {
        "name": name,
        "category": category,
        "goal_blueprints": blueprints,
        "duration_days": duration_days,
        "check_in_cadence_days": cadence,
    }
    wok, dok = _template_geometry_ok(rec)
    if not wok:
        err(E_TEMPLATE_WEIGHT_SUM, "goal weights must sum to 100 and ranges must hold")
    if not dok:
        err(E_TEMPLATE_CADENCE, "duration_days must be divisible by check_in_cadence_days")
    rec2 = new_record()
    rec2.update(rec)
    rec2.update({
        "hr_org_unit_id": ou["id"],
        "template_status": "DRAFT",
        "published_at": None,
        "published_version": None,
    })
    db.templates[rec2["id"]] = rec2
    return ok_object(public(rec2), 201)


@bp.get("/hr-org-units/<ouId>/pip-templates")
def list_templates(ouId):
    uid, role = auth()
    require_role(role, READERS)
    ou = resolve_ou(ouId)
    filters = {
        "template_status": request.args.get("template_status"),
        "category": request.args.get("category"),
    }
    records = [t for t in db.templates.values() if t["hr_org_unit_id"] == ou["id"]]
    return list_response(records, filters)


@bp.get("/hr-org-units/<ouId>/pip-templates/<templateId>")
def get_template(ouId, templateId):
    uid, role = auth()
    require_role(role, READERS)
    ou, t = resolve_template(ouId, templateId)
    return ok_object(public(t))


@bp.post("/hr-org-units/<ouId>/pip-templates/<templateId>/publish")
def publish_template(ouId, templateId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, t = resolve_template(ouId, templateId)
    if t["template_status"] != "DRAFT":
        err(E_INVALID_STATE, "template is not DRAFT")
    wok, dok = _template_geometry_ok(t)
    if not wok:
        err(E_TEMPLATE_WEIGHT_SUM, "goal weights must sum to 100 and ranges must hold")
    if not dok:
        err(E_TEMPLATE_CADENCE, "duration_days must be divisible by check_in_cadence_days")
    ou["pip_policy_version"] += 1
    touch(ou)
    t["template_status"] = "PUBLISHED"
    t["published_at"] = ou["current_utc"]
    t["published_version"] = ou["pip_policy_version"]
    touch(t)
    return ok_object(public(t))


@bp.post("/hr-org-units/<ouId>/pip-templates/<templateId>/retire")
def retire_template(ouId, templateId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, t = resolve_template(ouId, templateId)
    if t["template_status"] != "PUBLISHED":
        err(E_INVALID_STATE, "template is not PUBLISHED")
    for pip in db.pips.values():
        if pip["template_id"] == t["id"] and \
                pip["status"] in ("DRAFT", "ISSUED", "ACTIVE", "EXTENDED"):
            err(E_TEMPLATE_IN_USE, "template is referenced by an in-flight PIP")
    t["template_status"] = "RETIRED"
    touch(t)
    return ok_object(public(t))


# ---------------------------------------------------------------------------
# Rating cycles
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/rating-cycles")
def create_cycle(ouId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou = resolve_ou(ouId)
    b = body()
    label = require_field(b, "label")
    ws_raw = require_field(b, "window_start")
    we_raw = require_field(b, "window_end")
    ws, we = parse_dt(ws_raw), parse_dt(we_raw)
    if ws is None or we is None:
        err(E_INVALID_REQUEST, "window_start/window_end must be ISO 8601 timestamps")
    rec = new_record()
    rec.update({
        "hr_org_unit_id": ou["id"],
        "label": label,
        "window_start": fmt_like(ws, ws_raw),
        "window_end": fmt_like(we, we_raw),
        "status": "OPEN",
    })
    db.cycles[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/rating-cycles")
def list_cycles(ouId):
    uid, role = auth()
    require_role(role, READERS)
    ou = resolve_ou(ouId)
    filters = {"status": request.args.get("status")}
    records = [c for c in db.cycles.values() if c["hr_org_unit_id"] == ou["id"]]
    return list_response(records, filters)


@bp.post("/hr-org-units/<ouId>/rating-cycles/<cycleId>/calibrate")
def calibrate_cycle(ouId, cycleId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, cyc = resolve_cycle(ouId, cycleId)
    if cyc["status"] != "OPEN":
        err(E_INVALID_STATE, "rating cycle is not OPEN")
    if parse_dt(ou["current_utc"]) < parse_dt(cyc["window_end"]):
        err(E_CYCLE_STILL_OPEN, "rating window has not closed")
    cyc["status"] = "CALIBRATION"
    touch(cyc)
    return ok_object(public(cyc))


@bp.post("/hr-org-units/<ouId>/rating-cycles/<cycleId>/publish")
def publish_cycle(ouId, cycleId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, cyc = resolve_cycle(ouId, cycleId)
    if cyc["status"] != "CALIBRATION":
        err(E_INVALID_STATE, "rating cycle is not CALIBRATION")
    cyc["status"] = "PUBLISHED"
    touch(cyc)
    return ok_object(public(cyc))


@bp.post("/hr-org-units/<ouId>/rating-cycles/<cycleId>/archive")
def archive_cycle(ouId, cycleId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, cyc = resolve_cycle(ouId, cycleId)
    if cyc["status"] != "PUBLISHED":
        err(E_INVALID_STATE, "rating cycle is not PUBLISHED")
    if parse_dt(ou["current_utc"]) < parse_dt(cyc["window_end"]) + days(365):
        err(E_CYCLE_TOO_RECENT, "rating cycle is too recent to archive")
    cyc["status"] = "ARCHIVED"
    touch(cyc)
    return ok_object(public(cyc))
