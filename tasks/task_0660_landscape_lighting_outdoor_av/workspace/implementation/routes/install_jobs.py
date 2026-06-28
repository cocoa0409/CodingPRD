"""InstallJob endpoints (PRD 3.5).

Branching fork-join: wiring branch + fixtures branch must both finish before
the job energizes (JOIN). complete-wiring energizes STAGED transformers;
complete-fixtures mounts PLANNED zoned fixtures (requires WIRED); the join flips
the project ACCEPTED->INSTALLED.
"""

from flask import Blueprint

from clock import clock
from common import (
    get_json_body,
    paginate,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from common import iso_format
from db import db
from errors import err
from lookups import get_install_job, get_project, get_quote
from middleware import get_auth, require_role
from response import success
from services.load import recompute_project_loads, recompute_transformer
from services.serialize import ser_install_job

bp = Blueprint("install_jobs", __name__)

READ_ROLES = {"InstallTech", "LightingDesigner", "OperationsAdmin"}


@bp.post("/install-jobs")
def create_install_job():
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    body = get_json_body()
    require_fields(body, ["project_id", "quote_id"])
    project_id = require_string(body, "project_id")
    quote_id = require_string(body, "quote_id")
    get_project(project_id)
    get_quote(quote_id)

    record = stamp_new(
        {
            "project_id": project_id,
            "quote_id": quote_id,
            "wiring_status": "PENDING",
            "fixtures_status": "PENDING",
            "status": "SCHEDULED",
        }
    )
    db.install_jobs[record["id"]] = record
    return success(ser_install_job(record), status=201)


@bp.get("/install-jobs/<jid>")
def read_install_job(jid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    j = get_install_job(jid)
    return success(ser_install_job(j), status=200)


@bp.get("/projects/<pid>/install-jobs")
def list_project_install_jobs(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [j for j in db.install_jobs.values() if j["project_id"] == pid]
    data, pagination = paginate(items, ser_install_job)
    return success(data, status=200, pagination=pagination)


@bp.post("/install-jobs/<jid>/start")
def start_install_job(jid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    j = get_install_job(jid)
    if j["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install job is not SCHEDULED.")
    quote = db.quotes.get(j["quote_id"])
    if quote is None or quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Referenced quote is not ACCEPTED.")
    j["status"] = "IN_PROGRESS"
    touch(j)
    return success(ser_install_job(j), status=200)


@bp.post("/install-jobs/<jid>/complete-wiring")
def complete_wiring(jid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    j = get_install_job(jid)
    if j["status"] != "IN_PROGRESS" or j["wiring_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Wiring cannot be completed in this state.")
    j["wiring_status"] = "WIRED"
    touch(j)
    # Cascade: energize every STAGED transformer on the project.
    for t in db.transformers.values():
        if t["project_id"] == j["project_id"] and t["status"] == "STAGED":
            t["status"] = "ENERGIZED"
            touch(t)
    _maybe_join(j)
    return success(ser_install_job(j), status=200)


@bp.post("/install-jobs/<jid>/complete-fixtures")
def complete_fixtures(jid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    j = get_install_job(jid)
    if j["status"] != "IN_PROGRESS" or j["fixtures_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Fixtures cannot be completed in this state.")
    # Priority 8: wiring must be WIRED before fixtures may be mounted.
    if j["wiring_status"] != "WIRED":
        raise err("ERR_WIRING_NOT_COMPLETE", "Wiring is not complete.")
    j["fixtures_status"] = "MOUNTED"
    touch(j)
    # Cascade: mount every PLANNED zoned fixture on the project.
    now_iso = iso_format(clock.now())
    touched_transformers = set()
    for f in db.fixtures.values():
        if (
            f["project_id"] == j["project_id"]
            and f["status"] == "PLANNED"
            and f.get("zone_id") is not None
        ):
            f["status"] = "INSTALLED"
            f["installed_at"] = now_iso
            touch(f)
            zone = db.zones.get(f["zone_id"])
            if zone is not None:
                touched_transformers.add(zone.get("transformer_id"))
    # Status set does not change committed load (PLANNED and INSTALLED both
    # count), but recompute keeps derived consistency. No-op recomputes won't
    # bump versions.
    for tid in touched_transformers:
        t = db.transformers.get(tid)
        if t is not None:
            recompute_transformer(t)
    _maybe_join(j)
    return success(ser_install_job(j), status=200)


@bp.post("/install-jobs/<jid>/cancel")
def cancel_install_job(jid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    j = get_install_job(jid)
    if j["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED job may be cancelled.")
    j["status"] = "CANCELLED"
    touch(j)
    return success(ser_install_job(j), status=200)


def _maybe_join(j):
    """JOIN: when both branches are complete, energize the job and flip the
    project ACCEPTED->INSTALLED (cascade)."""
    if (
        j["status"] == "IN_PROGRESS"
        and j["wiring_status"] == "WIRED"
        and j["fixtures_status"] == "MOUNTED"
    ):
        j["status"] = "ENERGIZED"
        touch(j)
        project = db.projects.get(j["project_id"])
        if project is not None and project["commercial_status"] == "ACCEPTED":
            project["commercial_status"] = "INSTALLED"
            touch(project)
            recompute_project_loads(project)
