"""Site measures (PRD 3.1). Recorded against a project; the first advances the
project DRAFT->MEASURED. Any prior RECORDED measure is SUPERSEDED."""

from flask import Blueprint, request

from common import (
    get_json_body,
    optional_number_ge,
    paginate,
    public,
    require_bool,
    require_fields,
    require_number_ge,
    require_number_gt,
    stamp_new,
    touch,
)
from db import db
from lookups import get_child_or_404, get_project_or_404
from middleware import get_auth, require_role
from response import success

bp = Blueprint("site_measures", __name__)


@bp.route("/projects/<project_id>/site-measures", methods=["POST"])
def create_measure(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["gross_area_sqft", "longest_run_ft", "slope_pct"])
    gross = require_number_gt(body, "gross_area_sqft", 0)
    obstruction = optional_number_ge(body, "obstruction_area_sqft", 0, 0)
    longest_run = require_number_gt(body, "longest_run_ft", 0)
    slope = require_number_ge(body, "slope_pct", 0)
    soil_drains_freely = require_bool(body, "soil_drains_freely", True)

    # State precondition for first-measure advance is checked below; recording a
    # measure is allowed on any project, but only the first advances DRAFT->MEASURED.
    # Supersede any prior RECORDED measure on this project.
    for m in db.site_measures.values():
        if m["project_id"] == project_id and m["status"] == "RECORDED":
            m["status"] = "SUPERSEDED"
            touch(m)

    rec = {
        "project_id": project_id,
        "gross_area_sqft": gross,
        "obstruction_area_sqft": obstruction,
        "longest_run_ft": longest_run,
        "slope_pct": slope,
        "soil_drains_freely": soil_drains_freely,
        "status": "RECORDED",
    }
    stamp_new(rec)
    db.site_measures[rec["id"]] = rec

    # First measure advances the project DRAFT->MEASURED.
    if project["workflow_status"] == "DRAFT":
        project["workflow_status"] = "MEASURED"
        touch(project)

    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/site-measures", methods=["GET"])
def list_measures(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    status_filter = request.args.get("status")
    items = [m for m in db.site_measures.values() if m["project_id"] == project_id]
    if status_filter is not None:
        items = [m for m in items if m["status"] == status_filter]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/site-measures/<site_measure_id>", methods=["GET"])
def get_measure(project_id, site_measure_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    rec = get_child_or_404(db.site_measures, site_measure_id, project_id, "Site measure")
    return success(public(rec), status=200)
