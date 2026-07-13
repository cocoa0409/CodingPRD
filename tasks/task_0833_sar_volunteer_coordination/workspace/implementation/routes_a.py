"""Routes: clock, incidents, tasks, teams, members, certifications."""
from flask import Blueprint

import store
import calc
import cascades
from serializers import serialize
from errors import ApiError
from core import (
    auth, get_or_404, body_json, ok, created, paginate_and_respond,
    vstr, venum, vnum, vint, vdt, vfk, varray_enum,
)

bp = Blueprint("routes_a", __name__)

ALL_ROLES = {"Coordinator", "IncidentCommander", "FinanceOfficer", "Member"}

INCIDENT_TYPES = {"WILDERNESS_SEARCH", "DISASTER", "URBAN", "WATER", "AIR_SEARCH"}
TASK_TYPES = {"HASTY", "GRID_SEARCH", "K9", "AIR_RECON", "EVAC", "CONTAINMENT"}
PRIORITIES = {"URGENT", "STANDARD", "LOW"}
TEAM_TYPES = {"GROUND", "K9", "AIR", "SWIFTWATER", "MOUNTAIN"}
MEMBER_ROLES = {"SEARCHER", "TEAM_LEADER", "K9_HANDLER", "PILOT"}
CERT_TYPES = {"WFR", "ICS_100", "TRACKER", "K9_AREA", "ROPE_TECH", "SWIFTWATER", "PILOT"}


def require_state(rec, allowed):
    if rec["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")


# =========================================================================
# Logical clock
# =========================================================================
@bp.route("/sar/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"Coordinator"})
    d = body_json()
    value = vdt(d, "to_iso8601", required=True)
    store.set_clock(value)
    return ok(None)


# =========================================================================
# Incidents
# =========================================================================
@bp.route("/sar/incidents", methods=["POST"])
def create_incident():
    auth({"Coordinator", "IncidentCommander"})
    d = body_json()
    rec = store.base_record("Incident")
    rec["name"] = vstr(d, "name")
    rec["incident_type"] = venum(d, "incident_type", INCIDENT_TYPES)
    rec["ics_incident_number"] = vstr(d, "ics_incident_number")
    rec["operational_period_hours"] = vint(d, "operational_period_hours", required=False, default=12)
    rec["status"] = "PLANNING"
    rec["total_approved_reimbursement_cents"] = 0
    store.incidents[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.incidents, incident_id)))


@bp.route("/sar/incidents", methods=["GET"])
def list_incidents():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.incidents.values(), serialize,
        [("status", "status"), ("incident_type", "incident_type")],
    )


@bp.route("/sar/incidents/<incident_id>/activate", methods=["POST"])
def activate_incident(incident_id):
    auth({"IncidentCommander"})
    inc = get_or_404(store.incidents, incident_id)
    require_state(inc, {"PLANNING"})
    inc["status"] = "ACTIVE"
    store.mutate(inc)
    return ok(serialize(inc))


@bp.route("/sar/incidents/<incident_id>/demobilize", methods=["POST"])
def demobilize_incident(incident_id):
    auth({"IncidentCommander"})
    inc = get_or_404(store.incidents, incident_id)
    require_state(inc, {"ACTIVE"})
    inc["status"] = "DEMOBILIZING"
    store.mutate(inc)
    return ok(serialize(inc))


@bp.route("/sar/incidents/<incident_id>/close", methods=["POST"])
def close_incident(incident_id):
    auth({"IncidentCommander"})
    inc = get_or_404(store.incidents, incident_id)
    require_state(inc, {"DEMOBILIZING"})
    if calc.incident_rollups(inc["id"])["active_task_count"] != 0:
        raise ApiError("ERR_INCIDENT_HAS_ACTIVE_TASKS")
    inc["status"] = "CLOSED"
    store.mutate(inc)
    return ok(serialize(inc))


@bp.route("/sar/incidents/<incident_id>/cancel", methods=["POST"])
def cancel_incident(incident_id):
    auth({"IncidentCommander"})
    inc = get_or_404(store.incidents, incident_id)
    require_state(inc, {"PLANNING", "ACTIVE"})
    inc["status"] = "CANCELLED"
    store.mutate(inc)
    cascades.incident_cancel_cascade(inc)
    return ok(serialize(inc))


# =========================================================================
# Tasks
# =========================================================================
@bp.route("/sar/tasks", methods=["POST"])
def create_task():
    auth({"Coordinator", "IncidentCommander"})
    d = body_json()
    rec = store.base_record("Task")
    rec["incident_id"] = vfk(d, "incident_id", store.incidents)
    rec["task_number"] = vstr(d, "task_number")
    rec["task_type"] = venum(d, "task_type", TASK_TYPES)
    rec["priority"] = venum(d, "priority", PRIORITIES, required=False, default="STANDARD")
    rec["segment_area_sqkm"] = vnum(d, "segment_area_sqkm", gt=0)
    rec["planned_searcher_hours"] = vnum(d, "planned_searcher_hours", ge=0)
    rec["required_cert_types"] = varray_enum(d, "required_cert_types", CERT_TYPES, default=[])
    rec["max_responders"] = vint(d, "max_responders", required=False, default=8)
    ps = vdt(d, "planned_start")
    pe = vdt(d, "planned_end")
    if store.parse_dt(pe) <= store.parse_dt(ps):
        raise ApiError("ERR_VALIDATION")
    rec["planned_start"] = ps
    rec["planned_end"] = pe
    rec["status"] = "DRAFT"
    rec["estimated_coverage_pct"] = None
    rec["actual_coverage_pct"] = None
    store.tasks[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.tasks, task_id)))


@bp.route("/sar/tasks", methods=["GET"])
def list_tasks():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.tasks.values(), serialize,
        [("incident_id", "incident_id"), ("status", "status"), ("task_type", "task_type")],
    )


@bp.route("/sar/tasks/<task_id>/assign", methods=["POST"])
def assign_task(task_id):
    auth({"IncidentCommander"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"DRAFT"})
    incident = store.incidents.get(task["incident_id"])
    if incident is None or incident["status"] != "ACTIVE":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
    task["estimated_coverage_pct"] = calc.coverage_estimate_pct(task)
    task["status"] = "ASSIGNED"
    store.mutate(task)
    return ok(serialize(task))


@bp.route("/sar/tasks/<task_id>/start", methods=["POST"])
def start_task(task_id):
    auth({"IncidentCommander", "Coordinator"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"ASSIGNED"})
    has_deployed = any(
        c["task_id"] == task["id"] and c["status"] == "DEPLOYED"
        for c in store.callouts.values()
    )
    if not has_deployed:
        raise ApiError("ERR_NO_DEPLOYED_RESPONDERS")
    task["status"] = "IN_PROGRESS"
    store.mutate(task)
    return ok(serialize(task))


@bp.route("/sar/tasks/<task_id>/suspend", methods=["POST"])
def suspend_task(task_id):
    auth({"IncidentCommander", "Coordinator"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"IN_PROGRESS"})
    task["status"] = "SUSPENDED"
    store.mutate(task)
    cascades.task_suspend_cascade(task)
    return ok(serialize(task))


@bp.route("/sar/tasks/<task_id>/resume", methods=["POST"])
def resume_task(task_id):
    auth({"IncidentCommander", "Coordinator"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"SUSPENDED"})
    task["status"] = "IN_PROGRESS"
    store.mutate(task)
    return ok(serialize(task))


@bp.route("/sar/tasks/<task_id>/debrief", methods=["POST"])
def debrief_task(task_id):
    auth({"IncidentCommander", "Coordinator"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"IN_PROGRESS"})
    task["actual_coverage_pct"] = calc.coverage_actual_pct(task)
    task["status"] = "DEBRIEFED"
    store.mutate(task)
    cascades.task_debrief_cascade(task)
    return ok(serialize(task))


@bp.route("/sar/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    auth({"IncidentCommander", "Coordinator"})
    task = get_or_404(store.tasks, task_id)
    require_state(task, {"DRAFT", "ASSIGNED", "IN_PROGRESS", "SUSPENDED"})
    task["status"] = "CANCELLED"
    store.mutate(task)
    cascades.task_cancel_cascade(task)
    return ok(serialize(task))


# =========================================================================
# Teams
# =========================================================================
@bp.route("/sar/teams", methods=["POST"])
def create_team():
    auth({"Coordinator"})
    d = body_json()
    rec = store.base_record("Team")
    rec["name"] = vstr(d, "name")
    rec["team_type"] = venum(d, "team_type", TEAM_TYPES)
    rec["base_location"] = vstr(d, "base_location")
    rec["status"] = "ACTIVE"
    store.teams[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/teams/<team_id>", methods=["GET"])
def get_team(team_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.teams, team_id)))


@bp.route("/sar/teams", methods=["GET"])
def list_teams():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.teams.values(), serialize,
        [("status", "status"), ("team_type", "team_type")],
    )


@bp.route("/sar/teams/<team_id>/deactivate", methods=["POST"])
def deactivate_team(team_id):
    auth({"Coordinator"})
    team = get_or_404(store.teams, team_id)
    require_state(team, {"ACTIVE"})
    team["status"] = "INACTIVE"
    store.mutate(team)
    return ok(serialize(team))


# =========================================================================
# Members
# =========================================================================
@bp.route("/sar/members", methods=["POST"])
def create_member():
    auth({"Coordinator"})
    d = body_json()
    rec = store.base_record("Member")
    rec["team_id"] = vfk(d, "team_id", store.teams)
    rec["full_name"] = vstr(d, "full_name")
    rec["email"] = vstr(d, "email")
    rec["member_role"] = venum(d, "member_role", MEMBER_ROLES)
    rec["status"] = "ACTIVE"
    store.members[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/members/<member_id>", methods=["GET"])
def get_member(member_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.members, member_id)))


@bp.route("/sar/members", methods=["GET"])
def list_members():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.members.values(), serialize,
        [("team_id", "team_id"), ("status", "status"), ("member_role", "member_role")],
    )


# =========================================================================
# Certifications
# =========================================================================
@bp.route("/sar/certifications", methods=["POST"])
def create_certification():
    auth({"Coordinator"})
    d = body_json()
    rec = store.base_record("Certification")
    rec["member_id"] = vfk(d, "member_id", store.members)
    rec["cert_type"] = venum(d, "cert_type", CERT_TYPES)
    rec["issued_date"] = vdt(d, "issued_date")
    rec["expires_date"] = vdt(d, "expires_date")
    store.certifications[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/certifications/<certification_id>", methods=["GET"])
def get_certification(certification_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.certifications, certification_id)))


@bp.route("/sar/certifications", methods=["GET"])
def list_certifications():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.certifications.values(), serialize,
        [("member_id", "member_id"), ("cert_type", "cert_type"), ("status", "status")],
    )
