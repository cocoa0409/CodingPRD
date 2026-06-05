"""Retention-release endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import helpers as h
import services
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_PROJECT_VERSION,
    ERR_RELEASE_EXCEEDS_HELD,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("retention_releases", __name__)


def _get_or_404(rid):
    r = db.retention_releases.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "RetentionRelease not found.")
    return r


@bp.post("/retention-releases")
def create_retention_release():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "amount_cents", "expected_project_version"])

    project_id = h.as_string(body["project_id"], "project_id")
    project = db.projects.get(project_id)
    if project is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    amount = h.as_int(body["amount_cents"], "amount_cents", minimum=1)
    expected = h.as_int(body["expected_project_version"], "expected_project_version")

    # OCC stale-version on create (priority 16).
    if expected != project["version"]:
        raise err(ERR_STALE_PROJECT_VERSION, "expected_project_version is stale.")

    record = {
        "project_id": project_id,
        "amount_cents": amount,
        "status": "REQUESTED",
        "approved_by_user_id": None,
    }
    db.stamp_create(record)
    db.retention_releases[record["id"]] = record
    return success(h.retention_release_out(record), status=201)


@bp.get("/retention-releases/<rid>")
def get_retention_release(rid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.retention_release_out(_get_or_404(rid)))


@bp.get("/retention-releases")
def list_retention_releases():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.retention_releases.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.retention_release_out(r) for r in page], pagination=meta)


@bp.post("/retention-releases/<rid>/approve")
def approve_retention_release(rid):
    uid, role = authenticate()
    require_role(role, {"Owner"})
    r = _get_or_404(rid)
    project = db.projects.get(r["project_id"])
    body = h.get_json()
    h.require_fields(body, ["expected_project_version"])
    expected = h.as_int(body["expected_project_version"], "expected_project_version")

    # State (priority 5): REQUESTED and project ACTIVE/SUBSTANTIALLY_COMPLETE.
    if r["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "RetentionRelease is not REQUESTED.")
    if project is None or project["status"] not in ("ACTIVE", "SUBSTANTIALLY_COMPLETE"):
        raise err(ERR_INVALID_STATE, "Project status does not permit release approval.")
    # ERR_RELEASE_EXCEEDS_HELD (priority 13) precedes ERR_STALE_PROJECT_VERSION (16).
    if r["amount_cents"] > project["retainage_held_cents"]:
        raise err(ERR_RELEASE_EXCEEDS_HELD, "amount_cents exceeds retainage_held_cents.")
    if expected != project["version"]:
        raise err(ERR_STALE_PROJECT_VERSION, "expected_project_version is stale.")

    r["status"] = "APPROVED"
    r["approved_by_user_id"] = uid
    db.touch(r)

    # Waterfall draw-down; recompute retainage_held; bump project version.
    services.retention_waterfall(project, r["amount_cents"])
    db.touch(project)
    return success(h.retention_release_out(r))


@bp.post("/retention-releases/<rid>/reject")
def reject_retention_release(rid):
    _uid, role = authenticate()
    require_role(role, {"Owner"})
    r = _get_or_404(rid)
    if r["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "RetentionRelease is not REQUESTED.")
    r["status"] = "REJECTED"
    db.touch(r)
    return success(h.retention_release_out(r))
