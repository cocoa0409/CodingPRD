"""MaterialSpec endpoints and the four-link conservation cascade (PRD §3.6)."""

from flask import Blueprint

import calc
import cascades
import helpers
import serializers
from auth import (ALL_ROLES, ROLE_CONSERVATOR, ROLE_FABRICATION_LEAD, ROLE_PROJECT_MANAGER,
                  endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row
from validate import bad, body_object, v_enum, v_int, v_num, v_str

bp = Blueprint("materials", __name__)

USED_IN_VALUES = ("CASE_INTERIOR", "CASE_EXTERIOR", "MOUNT", "GRAPHIC", "INTERACTIVE_HOUSING")
ODDY_RESULTS = ("PASS", "TEMPORARY", "FAIL", "UNTESTED")
MATERIAL_DECISIONS = ("APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT")


def _verdict_of(material):
    return calc.material_verdict(material["used_in"], material["oddy_test_result"],
                                material["voc_mg_per_m2_day"], material["formaldehyde_ppm"],
                                material["cure_days"])


@bp.route("/exhibit-projects/<pid>/material-specs", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD, ROLE_CONSERVATOR])
def create_material(pid):
    project = helpers.get_project(pid)
    body = body_object()
    material_name = v_str(body, "material_name", 1, 120)
    used_in = v_enum(body, "used_in", USED_IN_VALUES)
    oddy = v_enum(body, "oddy_test_result", ODDY_RESULTS)
    voc = v_num(body, "voc_mg_per_m2_day", ge=0)
    formaldehyde = v_num(body, "formaldehyde_ppm", ge=0)
    cure_days = v_int(body, "cure_days", minimum=0, maximum=365)

    helpers.require_unique(db.materials, project["id"], "material_name", material_name)
    # Step 10: a material substitution mid-fabrication is normal, so FABRICATION is allowed.
    helpers.require_phase(project, ("INTERPRETIVE", "SCHEMATIC", "DESIGN_DEV", "FABRICATION"))

    material = new_row("materials", {
        "project_id": project["id"],
        "material_name": material_name,
        "used_in": used_in,
        "oddy_test_result": oddy,
        "voc_mg_per_m2_day": voc,
        "formaldehyde_ppm": formaldehyde,
        "cure_days": cure_days,
        "verdict": None,
        "status": "SUBMITTED",
        "conditions": None,
        "decided_at": None,
    })
    material["verdict"] = _verdict_of(material)
    db.materials[material["id"]] = material
    # A pending material alone makes an otherwise clean project RESTRICTED.
    touch(project)
    return object_response(serializers.material_json(material), 201)


@bp.route("/exhibit-projects/<pid>/material-specs", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_materials(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    verdict = query_filter("verdict")
    used_in = query_filter("used_in")
    rows = helpers.rows_of_project(db.materials, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if verdict is not None:
        rows = [r for r in rows if r["verdict"] == verdict]
    if used_in is not None:
        rows = [r for r in rows if r["used_in"] == used_in]
    return list_response(rows, serializers.material_json, limit, offset)


@bp.route("/material-specs/<material_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_material(material_id):
    material = helpers.get_material(material_id)
    return object_response(serializers.material_json(material))


@bp.route("/material-specs/<material_id>/shop-drawings", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_material_drawings(material_id):
    material = helpers.get_material(material_id)
    limit, offset = pagination()
    status = query_filter("status")
    rows = helpers.drawings_of_material(material["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.drawing_json, limit, offset)


@bp.route("/material-specs/<material_id>/submit-for-conservation", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD, ROLE_PROJECT_MANAGER])
def submit_material(material_id):
    material = helpers.get_material(material_id)
    project = helpers.owning_project(material)

    # §3.6: resubmitting from REJECTED clears that rejection's contribution to
    # conservation_block_count, so the sample's own block does not bar its rework.
    helpers.require_not_frozen(project, exclude_material_id=material["id"])
    if material["status"] not in ("SUBMITTED", "REJECTED", "APPROVED", "CONDITIONAL"):
        raise ApiError("ERR_INVALID_MATERIAL_STATE")
    if material["oddy_test_result"] == "UNTESTED":
        raise ApiError("ERR_INVALID_MATERIAL_STATE",
                       "An untested sample cannot be put in front of a conservator.")

    previous = material["status"]
    # The verdict is re-derived so a reformulated sample is judged on current data.
    material["verdict"] = _verdict_of(material)
    if previous == "CONDITIONAL":
        material["conditions"] = None
    material["status"] = "CONSERVATOR_REVIEW"
    # Every shop drawing already issued keeps its status through the resubmission.
    touch(material)
    touch(project)
    return object_response(serializers.material_json(material))


@bp.route("/material-specs/<material_id>/conservator-decision", methods=["POST"])
@endpoint(roles=[ROLE_CONSERVATOR])
def decide_material(material_id):
    material = helpers.get_material(material_id)
    project = helpers.owning_project(material)
    body = body_object()
    decision = v_enum(body, "decision", MATERIAL_DECISIONS)
    conditions = v_str(body, "conditions", None, None, required=False, default=None)
    if decision == "APPROVE_WITH_CONDITIONS" and (conditions is None or conditions.strip() == ""):
        bad("A conditional clearance requires a non-blank 'conditions' string.")

    if material["status"] != "CONSERVATOR_REVIEW":
        raise ApiError("ERR_INVALID_MATERIAL_STATE")

    verdict = material["verdict"]
    if decision == "APPROVE":
        if verdict != "CONSERVATION_SAFE":
            raise ApiError("ERR_OFFGASSING_LIMIT_EXCEEDED")
        material["status"] = "APPROVED"
        material["conditions"] = None
    elif decision == "APPROVE_WITH_CONDITIONS":
        if verdict not in ("CONSERVATION_SAFE", "CONDITIONAL_SAFE"):
            raise ApiError("ERR_OFFGASSING_LIMIT_EXCEEDED")
        material["status"] = "CONDITIONAL"
        material["conditions"] = conditions
    else:
        material["status"] = "REJECTED"
        material["decided_at"] = db.now()
        touch(material)
        # The deepest cascade in the system: drawing void -> money release ->
        # case revert -> object and slot release.
        cascades.material_rejection_cascade(material)
        touch(project)
        return object_response(serializers.material_json(material))

    material["decided_at"] = db.now()
    touch(material)
    return object_response(serializers.material_json(material))
