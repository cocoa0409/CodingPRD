"""Inspection endpoints + Warranty issuance (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations

bp = Blueprint("inspections", __name__)


def _next_attempt_no(project_id):
    max_attempt = 0
    for i in db.inspections.values():
        if i["project_id"] == project_id:
            max_attempt = max(max_attempt, i["attempt_no"])
    return max_attempt + 1


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_roles({"InstallManager"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    install_job_id = common.require_field(
        body, "install_job_id", expected_types=["string"])

    # existence left-to-right: project then install job (priority 4)
    project = common.get_project(project_id)
    job = common.get_install_job(install_job_id)

    # state (priority 5): project INSTALLING and the job INSTALLED
    if project["status"] != "INSTALLING":
        raise errors.invalid_state("Project must be INSTALLING to schedule inspection.")
    if job["progress_status"] != "INSTALLED":
        raise errors.invalid_state("The install job must be INSTALLED.")

    entity = {
        "project_id": project_id,
        "install_job_id": install_job_id,
        "attempt_no": _next_attempt_no(project_id),
        "result": "SCHEDULED",
        "punchlist_items": 0,
    }
    common.stamp_create(entity)
    db.inspections[entity["id"]] = entity

    project["status"] = "INSPECTING"
    common.touch(project)
    return response.success(serialize.inspection(entity), status=201)


@bp.route("/inspections/<iid>/pass", methods=["POST"])
def pass_inspection(iid):
    require_roles({"Inspector"})
    body = common.get_json()
    inspection = common.get_inspection(iid)
    project = common.get_project(inspection["project_id"])

    # state (priority 5)
    if inspection["result"] != "SCHEDULED":
        raise errors.invalid_state("Inspection must be SCHEDULED to pass.")
    if project["status"] != "INSPECTING":
        raise errors.invalid_state("Project must be INSPECTING.")

    # punchlist guard (priority 20): pass requires punchlist_items == 0
    punchlist_items = common.optional_field(
        body, "punchlist_items", 0, expected_types=["integer"],
        validator=lambda v: v >= 0)
    if punchlist_items != 0:
        raise errors.ApiError(
            errors.ERR_PUNCHLIST_REQUIRED, 422,
            "A passing inspection must carry zero punchlist items.")

    inspection["result"] = "PASSED"
    common.touch(inspection)

    # issue warranty (calc warranty_term)
    structure_type = project["structure_type"]
    term_years = calculations.warranty_term(structure_type)
    starts_at = db.now()
    expires_at = starts_at + timedelta(days=term_years * 365)
    warranty = {
        "project_id": project["id"],
        "structure_type": structure_type,
        "term_years": term_years,
        "starts_at": starts_at,
        "expires_at": expires_at,
    }
    # Warranty is immutable: only id + created_at (no updated_at / version).
    common.stamp_create(warranty, with_version=False)
    db.warranties[warranty["id"]] = warranty

    project["status"] = "COMPLETED"
    common.touch(project)
    return response.success(serialize.inspection(inspection), status=200)


@bp.route("/inspections/<iid>/fail", methods=["POST"])
def fail_inspection(iid):
    require_roles({"Inspector"})
    body = common.get_json()

    punchlist_items = common.require_field(
        body, "punchlist_items", expected_types=["integer"],
        validator=lambda v: v >= 0)

    inspection = common.get_inspection(iid)
    project = common.get_project(inspection["project_id"])

    # state (priority 5)
    if inspection["result"] != "SCHEDULED":
        raise errors.invalid_state("Inspection must be SCHEDULED to fail.")
    if project["status"] != "INSPECTING":
        raise errors.invalid_state("Project must be INSPECTING.")

    # punchlist guard (priority 20): fail requires punchlist_items >= 1
    if punchlist_items < 1:
        raise errors.ApiError(
            errors.ERR_PUNCHLIST_REQUIRED, 422,
            "A failing inspection requires at least one punchlist item.")

    inspection["result"] = "FAILED_PUNCHLIST"
    inspection["punchlist_items"] = punchlist_items
    common.touch(inspection)

    # reopen the install job for rework
    job = db.install_jobs.get(inspection["install_job_id"])
    if job is not None:
        job["progress_status"] = "IN_PROGRESS"
        common.touch(job)

    project["status"] = "INSTALLING"
    common.touch(project)
    return response.success(serialize.inspection(inspection), status=200)
