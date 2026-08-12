"""Project endpoints (PRD 3.1, 3.9 close-out)."""
import uuid

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ACTIVATION_INCOMPLETE,
    ERR_CLOSEOUT_INCOMPLETE,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_project
from util import (
    as_enum,
    as_int,
    as_str,
    check,
    get_body,
    new_entity,
    req_present,
    touch,
)

bp = Blueprint("projects", __name__)


@bp.post("/projects")
@require_roles("OwnerEngineer")
def create_project():
    body = get_body()
    name = as_str(req_present(body, "name"), "name")
    basis = as_enum(
        req_present(body, "measurement_basis"), "measurement_basis", ["IN_PLACE", "SCOW"]
    )
    base_rate = as_int(req_present(body, "base_rate_cents_per_cy"), "base_rate_cents_per_cy")
    check(base_rate > 0, "base_rate_cents_per_cy must be > 0")
    standby_rate = as_int(
        req_present(body, "standby_rate_cents_per_hour"), "standby_rate_cents_per_hour"
    )
    check(standby_rate > 0, "standby_rate_cents_per_hour must be > 0")
    ld_rate = as_int(
        req_present(body, "liquidated_damages_cents_per_day"),
        "liquidated_damages_cents_per_day",
    )
    check(ld_rate >= 0, "liquidated_damages_cents_per_day must be >= 0")
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "measurement_basis": basis,
            "base_rate_cents_per_cy": base_rate,
            "standby_rate_cents_per_hour": standby_rate,
            "liquidated_damages_cents_per_day": ld_rate,
            "status": "PLANNED",
            # No ISSUED permit governs a fresh project: SUSPENDED (PRD 2.6).
            "compliance_posture": "SUSPENDED",
            "allowed_days_frozen": None,
            "total_certified_cents": 0,
            "total_paid_cents": 0,
        }
    )
    store.projects[rec["id"]] = rec
    return ok(serialize_project(rec), 201)


def _get_project(pid):
    project = store.projects.get(pid)
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    return project


@bp.get("/projects/<pid>")
@require_roles(*ALL_ROLES)
def get_project(pid):
    return ok(serialize_project(_get_project(pid)))


@bp.get("/projects")
@require_roles(*ALL_ROLES)
def list_projects():
    return list_response(store.projects, serialize_project, ["status", "compliance_posture"])


@bp.post("/projects/<pid>/activate")
@require_roles("OwnerEngineer")
def activate_project(pid):
    project = _get_project(pid)
    if project["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Only a PLANNED project can be activated", 409)
    has_reach = any(r["project_id"] == pid for r in store.reaches.values())
    has_permit = any(
        p["project_id"] == pid and p["status"] == "ISSUED" for p in store.permits.values()
    )
    approved = [
        p for p in store.plans.values() if p["project_id"] == pid and p["status"] == "APPROVED"
    ]
    if not (has_reach and has_permit and approved):
        raise ApiError(
            ERR_ACTIVATION_INCOMPLETE,
            "Activation requires at least one Reach, one ISSUED Permit, and one "
            "APPROVED DredgePlan",
            409,
        )
    # Freeze allowed days from the most recently approved plan (snapshot; later
    # supersedes never re-freeze it).
    approved.sort(key=lambda p: p.get("_approved_seq", 0))
    project["allowed_days_frozen"] = approved[-1]["risk_adjusted_duration_days"]
    project["status"] = "ACTIVE"
    touch(project)
    return ok(serialize_project(project))


@bp.post("/projects/<pid>/close-out")
@require_roles("OwnerEngineer")
def close_out_project(pid):
    project = _get_project(pid)
    if project["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE project can be closed out", 409)
    problems = []
    if any(
        r["project_id"] == pid and r["status"] != "ACCEPTED" for r in store.reaches.values()
    ):
        problems.append("not every reach is ACCEPTED")
    if any(
        e["_project_id"] == pid and e["status"] in ("ACTIVE", "SHUTDOWN")
        for e in store.events.values()
    ):
        problems.append("open dredge events remain")
    if any(
        t["_project_id"] == pid and t["status"] == "REPORTED" for t in store.tickets.values()
    ):
        problems.append("REPORTED placement tickets remain")
    if any(
        c["project_id"] == pid and c["status"] in ("SUBMITTED", "APPROVED")
        for c in store.claims.values()
    ):
        problems.append("unsettled standby claims remain")
    if not any(
        c["project_id"] == pid and c["certificate_type"] == "FINAL" and c["status"] == "PAID"
        for c in store.certs.values()
    ):
        problems.append("no PAID FINAL certificate exists")
    if problems:
        raise ApiError(ERR_CLOSEOUT_INCOMPLETE, "; ".join(problems), 409)
    project["status"] = "CLOSED_OUT"
    touch(project)
    return ok(serialize_project(project))
