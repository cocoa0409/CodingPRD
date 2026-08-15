"""Cut programs, nesting yield, and the lock gates (PRD §3.3, OCC per §2.7)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.calculations import nesting_yield, toolings_for_program
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_cut_program, pub, req_enum,
    req_int, req_str, stamp_new, touch,
)
from services.workflows import obsolete_cut_program

bp = Blueprint("cut_programs", __name__)

METHODS = ("DIE_CUT", "CNC_ROUTE")
NESTABLE_SPEC_STATES = ("SUBMITTED", "IN_VALIDATION", "VALIDATED", "APPROVED")


@bp.route("/cut-programs", methods=["POST"])
def create_cut_program():
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    data = body()
    package_spec_id = req_str(data, "package_spec_id")
    method = req_enum(data, "method", METHODS)
    expected_version = req_int(data, "expected_package_spec_version")
    machine_seconds = None
    if method == "CNC_ROUTE":
        # Required for CNC_ROUTE; omitted is ERR_INVALID_REQUEST. Ignored for DIE_CUT.
        machine_seconds = req_int(data, "machine_seconds_per_part", minimum=1)
    supersedes_id = None
    if "supersedes_cut_program_id" in data and data["supersedes_cut_program_id"] is not None:
        supersedes_id = req_str(data, "supersedes_cut_program_id")

    spec = get_or_404(db.package_specs, package_spec_id, "PackageSpec")
    superseded = None
    if supersedes_id is not None:
        superseded = get_or_404(db.cut_programs, supersedes_id, "CutProgram")

    if expected_version != spec["version"]:
        raise ApiError(
            errors.ERR_STALE_SPEC_VERSION,
            "expected_package_spec_version does not equal the spec's current version",
            412,
        )
    if spec["status"] not in NESTABLE_SPEC_STATES:
        raise ApiError(
            errors.ERR_INVALID_STATE,
            f"Cannot create a cut program against a spec in {spec['status']}",
            409,
        )
    if superseded is not None and superseded["status"] != "LOCKED":
        raise ApiError(
            errors.ERR_INVALID_STATE,
            f"supersedes_cut_program_id must reference a LOCKED program, got {superseded['status']}",
            409,
        )

    rec = stamp_new({
        "package_spec_id": package_spec_id,
        "method": method,
        "machine_seconds_per_part": machine_seconds,
        "supersedes_cut_program_id": supersedes_id,
        "parts_per_sheet": None,
        "sheet_utilization_pct": None,
        "offcut_sqft_per_sheet": None,
        "status": "DRAFT",
    })
    db.cut_programs[rec["id"]] = rec
    # Creating a cut program mutates its parent: spec version increments by 1.
    touch(spec)
    if superseded is not None:
        obsolete_cut_program(superseded)
    return success_object(pub(rec), 201)


@bp.route("/cut-programs", methods=["GET"])
def list_cut_programs():
    return list_many(
        db.cut_programs, owner_of_cut_program,
        ("package_spec_id", "supersedes_cut_program_id", "status", "method"),
    )


@bp.route("/cut-programs/<rid>", methods=["GET"])
def get_cut_program(rid):
    return get_single(db.cut_programs, rid, owner_of_cut_program, "CutProgram")


@bp.route("/cut-programs/<rid>/nest", methods=["POST"])
def nest_cut_program(rid):
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    rec = get_or_404(db.cut_programs, rid, "CutProgram")
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot nest a program in {rec['status']}", 409)
    spec = db.package_specs.get(rec["package_spec_id"])
    if spec is None or spec["status"] not in NESTABLE_SPEC_STATES:
        raise ApiError(
            errors.ERR_INVALID_STATE,
            "Nesting requires the spec to be SUBMITTED, IN_VALIDATION, VALIDATED, or APPROVED",
            409,
        )
    material = db.materials.get(spec["material_id"])
    parts, util, offcut = nesting_yield(
        spec["part_length_in"], spec["part_width_in"],
        material["sheet_length_in"], material["sheet_width_in"],
    )
    rec["parts_per_sheet"] = parts
    rec["sheet_utilization_pct"] = util
    rec["offcut_sqft_per_sheet"] = offcut
    rec["status"] = "NESTED"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/cut-programs/<rid>/lock", methods=["POST"])
def lock_cut_program(rid):
    user_id, role = get_auth_context()
    require_role(role, ("DesignEngineer",))
    rec = get_or_404(db.cut_programs, rid, "CutProgram")
    if rec["status"] != "NESTED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot lock a program in {rec['status']}", 409)
    spec = db.package_specs.get(rec["package_spec_id"])
    material = db.materials.get(spec["material_id"]) if spec else None
    # Gate 1: cushioning safety margin re-checked at lock time (material's CURRENT ild).
    if material is None or spec is None or material["ild_lb_25"] < spec["required_ild_lb"]:
        raise ApiError(
            errors.ERR_ILD_SAFETY_MARGIN,
            "Material ild_lb_25 is below the spec's required_ild_lb at lock time",
            422,
        )
    # Gate 2: feasibility.
    if not rec["parts_per_sheet"] or rec["parts_per_sheet"] <= 0:
        raise ApiError(
            errors.ERR_UTILIZATION_INFEASIBLE,
            "parts_per_sheet is zero; the part does not fit the sheet",
            422,
        )
    # Gate 3: DIE_CUT requires an existing tooling that is IN_SERVICE.
    if rec["method"] == "DIE_CUT":
        cands = toolings_for_program(rec["id"])
        if not cands:
            raise ApiError(
                errors.ERR_TOOLING_REQUIRED,
                "A DIE_CUT program cannot be locked without a Tooling record",
                422,
            )
        if not any(t["status"] == "IN_SERVICE" for t in cands):
            raise ApiError(
                errors.ERR_TOOLING_NOT_IN_SERVICE,
                "No IN_SERVICE tooling exists for this program",
                409,
            )
    rec["status"] = "LOCKED"
    touch(rec)
    # Locking marks the program as the spec's active manufacturing definition:
    # spec version increments by 1.
    if spec is not None:
        touch(spec)
    return success_object(pub(rec))
