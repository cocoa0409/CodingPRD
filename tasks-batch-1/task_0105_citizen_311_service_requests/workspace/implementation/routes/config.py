"""Reference configuration endpoints: categories, jurisdictions, departments,
sla-policies, citizens, agents (PRD §3.1)."""
import re

from flask import Blueprint

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response
from services import calc

bp = Blueprint("config", __name__)

_CODE_RE = re.compile(r"^[A-Z_]+$")


# ---------------- ServiceCategory ----------------

@bp.route("/categories", methods=["POST"])
def create_category():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    name = validate.require_str(data, "name")
    code = validate.require_str(data, "code")
    if not _CODE_RE.match(code):
        raise errors.invalid_request("code must be uppercase letters A-Z and underscore.")
    default_priority = validate.opt_enum(data, "default_priority", validate.PRIORITIES, "STANDARD")
    default_department_id = validate.require_str(data, "default_department_id")
    requires_geolocation = validate.opt_bool(data, "requires_geolocation", True)
    active = validate.opt_bool(data, "active", True)

    # Existence (priority 3): default_department_id must resolve.
    if default_department_id not in db.departments:
        raise errors.not_found("Department not found: {}".format(default_department_id))

    # Uniqueness (business constraint).
    for c in db.categories.values():
        if c["name"] == name:
            raise errors.invalid_request("Category name must be unique.")
        if c["code"] == code:
            raise errors.invalid_request("Category code must be unique.")

    rec = {
        "name": name,
        "code": code,
        "default_priority": default_priority,
        "default_department_id": default_department_id,
        "requires_geolocation": requires_geolocation,
        "active": active,
    }
    db.stamp_common(rec)
    db.categories[rec["id"]] = rec
    return response.object_response(serialize.view("category", rec), 201)


@bp.route("/categories/<cid>", methods=["GET"])
def get_category(cid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent", "Citizen"})
    rec = db.categories.get(cid)
    if rec is None:
        raise errors.not_found("Category not found.")
    return response.object_response(serialize.view("category", rec))


@bp.route("/categories", methods=["GET"])
def list_categories():
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent", "Citizen"})
    limit, offset = validate.pagination()
    from flask import request
    dept_filter = request.args.get("default_department_id")
    active_filter = request.args.get("active")

    def pred(r):
        if dept_filter is not None and r["default_department_id"] != dept_filter:
            return False
        if active_filter is not None:
            want = active_filter.lower() == "true"
            if r["active"] != want:
                return False
        return True

    rows = db.ordered(db.categories, pred)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("category", page), limit, offset, total)


@bp.route("/categories/<cid>/sla-policies", methods=["GET"])
def list_category_sla_policies(cid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    if cid not in db.categories:
        raise errors.not_found("Category not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.sla_policies, lambda r: r["category_id"] == cid)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("sla_policy", page), limit, offset, total)


# ---------------- Jurisdiction ----------------

@bp.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    name = validate.require_str(data, "name")
    min_lat = validate.require_number(data, "min_lat")
    max_lat = validate.require_number(data, "max_lat")
    min_lng = validate.require_number(data, "min_lng")
    max_lng = validate.require_number(data, "max_lng")
    override_department_id = validate.opt_str(data, "override_department_id", None)

    if override_department_id is not None and override_department_id not in db.departments:
        raise errors.not_found("Override department not found.")

    for j in db.jurisdictions.values():
        if j["name"] == name:
            raise errors.invalid_request("Jurisdiction name must be unique.")

    rec = {
        "name": name,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lng": min_lng,
        "max_lng": max_lng,
        "override_department_id": override_department_id,
    }
    db.stamp_common(rec)
    db.jurisdictions[rec["id"]] = rec
    return response.object_response(serialize.view("jurisdiction", rec), 201)


@bp.route("/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    rec = db.jurisdictions.get(jid)
    if rec is None:
        raise errors.not_found("Jurisdiction not found.")
    return response.object_response(serialize.view("jurisdiction", rec))


@bp.route("/jurisdictions/<jid>/blackout-windows", methods=["GET"])
def list_jurisdiction_blackout_windows(jid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    if jid not in db.jurisdictions:
        raise errors.not_found("Jurisdiction not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.windows,
                      lambda r: r["window_type"] == "BLACKOUT" and r["jurisdiction_id"] == jid)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("window", page), limit, offset, total)


# ---------------- Department ----------------

@bp.route("/departments", methods=["POST"])
def create_department():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    name = validate.require_str(data, "name")
    backlog_threshold = validate.require_int(data, "backlog_threshold")
    if backlog_threshold < 1:
        raise errors.invalid_request("backlog_threshold must be >= 1.")
    for d in db.departments.values():
        if d["name"] == name:
            raise errors.invalid_request("Department name must be unique.")
    rec = {
        "name": name,
        "open_work_order_count": 0,
        "backlog_threshold": backlog_threshold,
        "congested": False,
    }
    db.stamp_common(rec)
    db.departments[rec["id"]] = rec
    return response.object_response(serialize.view("department", rec), 201)


@bp.route("/departments/<did>", methods=["GET"])
def get_department(did):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent"})
    rec = db.departments.get(did)
    if rec is None:
        raise errors.not_found("Department not found.")
    return response.object_response(serialize.view("department", rec))


@bp.route("/departments/<did>/satisfaction", methods=["GET"])
def department_satisfaction(did):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    if did not in db.departments:
        raise errors.not_found("Department not found.")
    result = calc.avg_satisfaction(did)
    return response.object_response(result)


@bp.route("/departments/<did>/jurisdictions", methods=["GET"])
def department_jurisdictions(did):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    if did not in db.departments:
        raise errors.not_found("Department not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.jurisdictions, lambda r: r["override_department_id"] == did)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("jurisdiction", page), limit, offset, total)


@bp.route("/departments/<did>/agents", methods=["GET"])
def department_agents(did):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent"})
    if did not in db.departments:
        raise errors.not_found("Department not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.agents, lambda r: r["department_id"] == did)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("agent", page), limit, offset, total)


@bp.route("/departments/<did>/maintenance-windows", methods=["GET"])
def list_department_maintenance_windows(did):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher"})
    if did not in db.departments:
        raise errors.not_found("Department not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.windows,
                      lambda r: r["window_type"] == "MAINTENANCE" and r["department_id"] == did)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("window", page), limit, offset, total)


# ---------------- SlaPolicy ----------------

@bp.route("/sla-policies", methods=["POST"])
def create_sla_policy():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    category_id = validate.require_str(data, "category_id")
    priority = validate.require_enum(data, "priority", validate.PRIORITIES)
    resolution_sla_hours = validate.require_int(data, "resolution_sla_hours")
    escalation_tier1_hours = validate.require_int(data, "escalation_tier1_hours")
    escalation_tier2_hours = validate.require_int(data, "escalation_tier2_hours")

    if category_id not in db.categories:
        raise errors.not_found("Category not found.")
    if resolution_sla_hours < 1:
        raise errors.invalid_request("resolution_sla_hours must be >= 1.")
    if escalation_tier1_hours < 0:
        raise errors.invalid_request("escalation_tier1_hours must be >= 0.")
    if escalation_tier2_hours <= escalation_tier1_hours:
        raise errors.invalid_request("escalation_tier2_hours must exceed escalation_tier1_hours.")

    for pol in db.sla_policies.values():
        if pol["category_id"] == category_id and pol["priority"] == priority:
            raise errors.invalid_request("(category_id, priority) must be unique.")

    rec = {
        "category_id": category_id,
        "priority": priority,
        "resolution_sla_hours": resolution_sla_hours,
        "escalation_tier1_hours": escalation_tier1_hours,
        "escalation_tier2_hours": escalation_tier2_hours,
    }
    db.stamp_common(rec)
    db.sla_policies[rec["id"]] = rec
    return response.object_response(serialize.view("sla_policy", rec), 201)


# ---------------- Citizen ----------------

@bp.route("/citizens", methods=["POST"])
def create_citizen():
    # Self-register: open operation under Anonymous role; no authentication.
    data = validate.body()
    email = validate.require_str(data, "email")
    full_name = validate.require_str(data, "full_name")
    notify_channel = validate.opt_enum(data, "notify_channel", validate.NOTIFY_CHANNELS, "EMAIL")
    for c in db.citizens.values():
        if c["email"] == email:
            raise errors.invalid_request("Citizen email must be unique.")
    rec = {
        "email": email,
        "full_name": full_name,
        "notify_channel": notify_channel,
    }
    db.stamp_common(rec)
    db.citizens[rec["id"]] = rec
    return response.object_response(serialize.view("citizen", rec), 201)


# ---------------- Agent ----------------

@bp.route("/agents", methods=["POST"])
def create_agent():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    department_id = validate.require_str(data, "department_id")
    full_name = validate.require_str(data, "full_name")
    is_supervisor = validate.opt_bool(data, "is_supervisor", False)
    if department_id not in db.departments:
        raise errors.not_found("Department not found.")
    rec = {
        "department_id": department_id,
        "full_name": full_name,
        "is_supervisor": is_supervisor,
    }
    db.stamp_common(rec)
    db.agents[rec["id"]] = rec
    return response.object_response(serialize.view("agent", rec), 201)
