"""DisplayDesign endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, require_number, touch, paginate,
    sort_by_created, serialize, recompute_compliance,
)

bp = Blueprint("designs", __name__)

GET_ROLES = ("PlatformAdmin", "ProgramManager", "Designer", "ComplianceOfficer", "ProductionPlanner")


def _get_design_or_404(design_id):
    d = db.designs.get(design_id)
    if not d:
        raise errors.err_not_found("Design not found")
    return d


@bp.route("/pop/designs", methods=["POST"])
@require_roles("Designer")
def create_design():
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    design_code = require_string(body, "design_code")
    width_in = require_number(body, "width_in", exclusive_min=0)
    height_in = require_number(body, "height_in", exclusive_min=0)
    depth_in = require_number(body, "depth_in", exclusive_min=0)
    weight_lb = require_number(body, "weight_lb", exclusive_min=0)
    material = require_string(body, "material")

    program = db.programs.get(program_id)
    if not program:
        raise errors.err_not_found("Program not found")

    # Uniqueness: design_code per program
    for d in db.designs.values():
        if d["program_id"] == program_id and d["design_code"] == design_code:
            raise errors.err_duplicate("design_code already exists in this program")

    design = new_common_fields()
    design.update({
        "program_id": program_id,
        "design_code": design_code,
        "width_in": width_in,
        "height_in": height_in,
        "depth_in": depth_in,
        "weight_lb": weight_lb,
        "material": material,
        "revision_number": 1,
        "status": "DRAFT",
    })
    recompute_compliance(design)
    db.designs[design["id"]] = design
    return response.success_object(serialize(design), 201)


@bp.route("/pop/designs/<design_id>", methods=["GET"])
def get_design(design_id):
    _, role = get_auth()
    if role not in GET_ROLES:
        raise errors.err_unauthorized()
    design = _get_design_or_404(design_id)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/programs/<program_id>/designs", methods=["GET"])
def list_program_designs(program_id):
    _, role = get_auth()
    if role not in GET_ROLES:
        raise errors.err_unauthorized()
    if not db.programs.get(program_id):
        raise errors.err_not_found("Program not found")
    items = sort_by_created([d for d in db.designs.values() if d["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(d) for d in page], limit, offset, total)


@bp.route("/pop/designs/<design_id>/submit", methods=["POST"])
@require_roles("Designer")
def submit_design(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "DRAFT":
        raise errors.err_invalid_state("Design is not in DRAFT")
    program = db.programs.get(design["program_id"])
    if not program or program["status"] != "DESIGN":
        raise errors.err_invalid_state("Parent program is not in DESIGN")
    recompute_compliance(design)
    design["status"] = "SUBMITTED"
    touch(design)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/designs/<design_id>/begin-review", methods=["POST"])
@require_roles("ComplianceOfficer")
def begin_review(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Design is not in SUBMITTED")
    design["status"] = "COMPLIANCE_REVIEW"
    touch(design)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/designs/<design_id>/approve", methods=["POST"])
@require_roles("ComplianceOfficer")
def approve_design(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "COMPLIANCE_REVIEW":
        raise errors.err_invalid_state("Design is not in COMPLIANCE_REVIEW")
    if design["compliance_result"] != "PASS":
        raise errors.err_compliance_failed("Design compliance_result is not PASS")
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_design_version")
    if expected is not None:
        if expected != design["version"]:
            raise errors.err_stale_version("expected_design_version does not match current design version")
    design["status"] = "APPROVED"
    touch(design)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/designs/<design_id>/reject", methods=["POST"])
@require_roles("ComplianceOfficer")
def reject_design(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "COMPLIANCE_REVIEW":
        raise errors.err_invalid_state("Design is not in COMPLIANCE_REVIEW")
    design["status"] = "REJECTED"
    touch(design)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/designs/<design_id>/revise", methods=["POST"])
@require_roles("Designer")
def revise_design(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "REJECTED":
        raise errors.err_invalid_state("Design is not in REJECTED")
    program = db.programs.get(design["program_id"])
    if not program or program["status"] != "DESIGN":
        raise errors.err_invalid_state("Parent program is not in DESIGN")
    design["status"] = "DRAFT"
    design["revision_number"] += 1
    touch(design)
    return response.success_object(serialize(design), 200)


@bp.route("/pop/designs/<design_id>/lock", methods=["POST"])
@require_roles("ProgramManager")
def lock_design(design_id):
    design = _get_design_or_404(design_id)
    if design["status"] != "APPROVED":
        raise errors.err_invalid_state("Design is not in APPROVED")
    has_run = any(r["design_id"] == design_id for r in db.production_runs.values())
    if not has_run:
        raise errors.err_invalid_state("No production run references this design")
    design["status"] = "LOCKED"
    touch(design)
    return response.success_object(serialize(design), 200)
