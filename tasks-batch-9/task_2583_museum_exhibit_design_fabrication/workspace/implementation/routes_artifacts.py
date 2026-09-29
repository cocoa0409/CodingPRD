"""Collection object (artifact) endpoints (PRD §3.4)."""

from flask import Blueprint

import helpers
import serializers
from auth import ALL_ROLES, ROLE_CURATOR, endpoint
from envelope import list_response, object_response, pagination, query_filter
from store import db, new_row
from validate import bad, body_object, v_enum, v_num, v_str

bp = Blueprint("artifacts", __name__)

MATERIAL_CLASSES = ("ORGANIC", "METAL", "PAPER", "TEXTILE", "COMPOSITE")
SECURITY_CLASSES = ("BASIC", "ENHANCED", "HIGH_VALUE")
CONDITION_STATUSES = ("STABLE", "FRAGILE", "UNSTABLE")


@bp.route("/exhibit-projects/<pid>/artifacts", methods=["POST"])
@endpoint(roles=[ROLE_CURATOR])
def create_artifact(pid):
    project = helpers.get_project(pid)
    body = body_object()
    accession = v_str(body, "accession_number", 1, 40)
    material_class = v_enum(body, "material_class", MATERIAL_CLASSES)
    rh_min = v_num(body, "required_rh_min_pct", gt=0, lt=100)
    rh_max = v_num(body, "required_rh_max_pct", gt=0, lt=100)
    max_lux = v_num(body, "max_lux", ge=0)
    security_class = v_enum(body, "security_class", SECURITY_CLASSES)
    condition_status = v_enum(body, "condition_status", CONDITION_STATUSES)
    if not rh_max > rh_min:
        bad("required_rh_max_pct must be strictly greater than required_rh_min_pct.")

    helpers.require_unique(db.artifacts, project["id"], "accession_number", accession)
    # Step 10: collection objects may be registered only in the three planning phases.
    helpers.require_phase(project, ("INTERPRETIVE", "SCHEMATIC", "DESIGN_DEV"))

    artifact = new_row("artifacts", {
        "project_id": project["id"],
        "assigned_case_id": None,
        "accession_number": accession,
        "material_class": material_class,
        "required_rh_min_pct": rh_min,
        "required_rh_max_pct": rh_max,
        "max_lux": max_lux,
        "security_class": security_class,
        "condition_status": condition_status,
        "placement_status": "UNPLACED",
    })
    db.artifacts[artifact["id"]] = artifact
    return object_response(serializers.artifact_json(artifact), 201)


@bp.route("/exhibit-projects/<pid>/artifacts", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_artifacts(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    placement_status = query_filter("placement_status")
    condition_status = query_filter("condition_status")
    assigned_case_id = query_filter("assigned_case_id")
    rows = helpers.rows_of_project(db.artifacts, project["id"])
    if placement_status is not None:
        rows = [r for r in rows if r["placement_status"] == placement_status]
    if condition_status is not None:
        rows = [r for r in rows if r["condition_status"] == condition_status]
    if assigned_case_id is not None:
        rows = [r for r in rows if r["assigned_case_id"] == assigned_case_id]
    return list_response(rows, serializers.artifact_json, limit, offset)


@bp.route("/artifacts/<artifact_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_artifact(artifact_id):
    artifact = helpers.get_artifact(artifact_id)
    return object_response(serializers.artifact_json(artifact))
