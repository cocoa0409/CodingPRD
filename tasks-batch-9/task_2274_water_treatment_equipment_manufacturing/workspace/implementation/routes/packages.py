"""Equipment packages, design review, release to fabrication and skids."""
from flask import Blueprint

import auth
import calc
import clock
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D, ceil_int

bp = Blueprint("packages", __name__)


def _duplicate_tag(stage_id, tag_number, exclude_id=None):
    for pkg in db.all_rows("equipment_packages"):
        if pkg["treatment_stage_id"] != stage_id:
            continue
        if exclude_id is not None and pkg["id"] == exclude_id:
            continue
        if pkg["tag_number"] == tag_number:
            fail("ERR_DUPLICATE_TAG_NUMBER",
                 "tag_number %s already exists on this stage" % tag_number)


def _screen(package_row, stage_row, material):
    project = domain.project_of_stage(stage_row)
    domain.screen_material(
        material,
        package_row["design_pressure_psig"],
        package_row["code_stamp_required"],
        domain.technology_of_stage(stage_row),
        domain.governing_profile_of(project) if project else None,
    )


# --------------------------------------------------------------- create/list --

@bp.post("/treatment-stages/<stage_id>/equipment-packages")
def create_package(stage_id):
    actor = auth.require("ApplicationEngineer")
    stage = domain.stage(stage_id)
    body = validate.body()
    material = validate.catalog_ref(body, "material_spec_id", "material_specs")
    validate.string(body, "material_spec_id")
    tag_number = validate.string(body, "tag_number", max_length=80)
    design_pressure = validate.number(body, "design_pressure_psig", exclusive_minimum=0)
    design_temp = validate.number(body, "design_temp_c")

    _duplicate_tag(stage["id"], tag_number)

    if stage["status"] == "SUPERSEDED":
        fail("ERR_STAGE_SUPERSEDED", "the parent treatment stage is superseded")

    technology = domain.technology_of_stage(stage)
    code_stamp = technology["requires_code_stamp"] if technology else "NONE"

    row = db.new_row("equipment_packages")
    row.update({
        "treatment_stage_id": stage["id"],
        "material_spec_id": material["id"],
        "tag_number": tag_number,
        "design_pressure_psig": design_pressure,
        "design_temp_c": design_temp,
        "code_stamp_required": code_stamp,
        "status": "DRAFT",
        "revision_round": 0,
        "designed_by_user_id": actor,
        "reviewed_by_user_id": None,
        "budgetary_cost_cents": 0,
        "firm_cost_cents": 0,
        "cost_variance_pct": D(0),
        "variance_flag": False,
        "approved_at": None,
        "released_at": None,
    })
    _screen(row, stage, material)
    domain.stamp_budgetary(row, stage)
    db.insert("equipment_packages", row)
    return response.created(serialize.row(row))


@bp.get("/equipment-packages")
def list_packages():
    auth.require(*auth.ROLES)
    stage_id = validate.string_filter("treatment_stage_id")
    material_spec_id = validate.string_filter("material_spec_id")
    status = validate.enum_filter("status", C.PACKAGE_STATUSES)
    rows = db.all_rows("equipment_packages")
    if stage_id:
        rows = [r for r in rows if r["treatment_stage_id"] == stage_id]
    if material_spec_id:
        rows = [r for r in rows if r["material_spec_id"] == material_spec_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/equipment-packages/<package_id>")
def get_package(package_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.package(package_id)))


# -------------------------------------------------------------------- revise --

@bp.patch("/equipment-packages/<package_id>")
def revise_package(package_id):
    auth.require("ApplicationEngineer")
    package = domain.package(package_id)
    body = validate.body()
    material = validate.catalog_ref(body, "material_spec_id", "material_specs")
    tag_number = validate.string(body, "tag_number", required=False, default=None,
                                 max_length=80)
    design_pressure = validate.number(
        body, "design_pressure_psig", required=False, default=None,
        exclusive_minimum=0)
    design_temp = validate.number(body, "design_temp_c", required=False, default=None)

    if tag_number is not None:
        _duplicate_tag(package["treatment_stage_id"], tag_number, package["id"])

    if package["status"] != "DRAFT":
        fail("ERR_PACKAGE_INVALID_STATE", "only a DRAFT package may be revised")
    stage = domain.stage_of_package(package)
    if stage is None or stage["status"] not in ("SELECTED", "ENGINEERED"):
        fail("ERR_STAGE_SUPERSEDED", "the parent treatment stage is superseded")

    if material is not None:
        package["material_spec_id"] = material["id"]
    if tag_number is not None:
        package["tag_number"] = tag_number
    if design_pressure is not None:
        package["design_pressure_psig"] = design_pressure
    if design_temp is not None:
        package["design_temp_c"] = design_temp

    current_material = db.get("material_specs", package["material_spec_id"])
    _screen(package, stage, current_material)
    domain.stamp_budgetary(package, stage)
    db.touch(package)
    return response.ok(serialize.row(package))


# --------------------------------------------------------- submit for review --

@bp.post("/equipment-packages/<package_id>/submit-for-review")
def submit_for_review(package_id):
    auth.require("ApplicationEngineer")
    package = domain.package(package_id)
    body = validate.body()
    validate.string(body, "submittal_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if package["status"] != "DRAFT":
        fail("ERR_PACKAGE_INVALID_STATE", "only a DRAFT package may be submitted")
    stage = domain.stage_of_package(package)
    if stage is None or stage["status"] not in ("SELECTED", "ENGINEERED"):
        fail("ERR_STAGE_SUPERSEDED", "the parent treatment stage is superseded")

    material = db.get("material_specs", package["material_spec_id"])
    _screen(package, stage, material)

    package["status"] = "IN_REVIEW"
    domain.stamp_budgetary(package, stage)
    db.touch(package)
    return response.ok(serialize.row(package))


# ------------------------------------------------------------ review decision --

@bp.post("/equipment-packages/<package_id>/review-decision")
def review_decision(package_id):
    actor = auth.require("DesignReviewer")
    package = domain.package(package_id)
    body = validate.body()
    decision = validate.enum(body, "decision", C.REVIEW_DECISIONS)
    validate.string(body, "review_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if package["status"] != "IN_REVIEW":
        fail("ERR_PACKAGE_INVALID_STATE", "only an IN_REVIEW package may be reviewed")
    stage = domain.stage_of_package(package)
    if stage is None or stage["status"] not in ("SELECTED", "ENGINEERED"):
        fail("ERR_STAGE_SUPERSEDED", "the parent treatment stage is superseded")
    domain.forbid_same_user(actor, package["designed_by_user_id"],
                            "ERR_SOD_DESIGNER_IS_REVIEWER")

    if decision == "REQUEST_REVISION":
        package["status"] = "DRAFT"
        package["revision_round"] = int(package["revision_round"]) + 1
        package["reviewed_by_user_id"] = actor
        db.touch(package)
        return response.ok(serialize.row(package))

    package["status"] = "APPROVED"
    package["approved_at"] = clock.now_iso()
    package["reviewed_by_user_id"] = actor
    material = db.get("material_specs", package["material_spec_id"])
    domain.stamp_firm(package, stage, material)
    db.touch(package)

    if stage["status"] == "SELECTED":
        stage["status"] = "ENGINEERED"
        db.touch(stage)

    project = domain.project_of_stage(stage)
    if project is not None:
        domain.recompute_posture(project)

    return response.ok(serialize.row(package))


# ------------------------------------------------------ release to fabrication --

@bp.post("/equipment-packages/<package_id>/release-for-fabrication")
def release_for_fabrication(package_id):
    auth.require("FabricationManager")
    package = domain.package(package_id)
    body = validate.body()
    validate.string(body, "release_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if package["status"] != "APPROVED":
        fail("ERR_PACKAGE_INVALID_STATE", "only an APPROVED package may be released")
    stage = domain.stage_of_package(package)
    if stage is None or stage["status"] != "ENGINEERED":
        fail("ERR_PACKAGE_INVALID_STATE",
             "the parent treatment stage is not ENGINEERED")
    project = domain.project_of_stage(stage)
    if project is None or project["status"] not in ("AWARDED", "IN_FABRICATION"):
        fail("ERR_INVALID_PROJECT_STATE",
             "release requires the project to be AWARDED or IN_FABRICATION")

    package["status"] = "RELEASED_FOR_FAB"
    package["released_at"] = clock.now_iso()
    db.touch(package)

    technology = domain.technology_of_stage(stage)
    footprint_sf = ceil_int(
        D(technology["footprint_sf_per_mgd"]) * D(stage["design_flow_mgd"])
    ) if technology else 0

    skid = db.new_row("skids")
    skid.update({
        "equipment_package_id": package["id"],
        "serial_no": "SKID-%s-%s" % (stage["stage_index"], package["revision_round"]),
        "footprint_sf": footprint_sf,
        "requires_exclusive_bay": package["code_stamp_required"] == "ASME_U",
        "mechanical_status": "FRAME_SET",
        "controls_status": "PANEL_BUILD",
        "fat_readiness": "NOT_READY",
        "rework_count": 0,
    })
    db.insert("skids", skid)

    if project["status"] == "AWARDED":
        project["status"] = "IN_FABRICATION"
        domain.recompute_posture(project)

    return response.ok(serialize.row(package))


# --------------------------------------------------------------------- skids --

@bp.get("/skids")
def list_skids():
    auth.require(*auth.ROLES)
    package_id = validate.string_filter("equipment_package_id")
    mechanical = validate.enum_filter("mechanical_status", C.MECHANICAL_STATUSES)
    controls = validate.enum_filter("controls_status", C.CONTROLS_STATUSES)
    readiness = validate.enum_filter("fat_readiness", C.FAT_READINESS)
    rows = db.all_rows("skids")
    if package_id:
        rows = [r for r in rows if r["equipment_package_id"] == package_id]
    if mechanical:
        rows = [r for r in rows if r["mechanical_status"] == mechanical]
    if controls:
        rows = [r for r in rows if r["controls_status"] == controls]
    if readiness:
        rows = [r for r in rows if r["fat_readiness"] == readiness]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/skids/<skid_id>")
def get_skid(skid_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.skid(skid_id)))


@bp.post("/skids/<skid_id>/milestones")
def skid_milestone(skid_id):
    auth.require("FabricationManager")
    skid = domain.skid(skid_id)
    body = validate.body()
    dimension = validate.enum(body, "dimension", C.MILESTONE_DIMENSIONS)
    to_state = validate.enum(
        body, "to_state", C.MECHANICAL_STATUSES + C.CONTROLS_STATUSES)
    validate.string(body, "milestone_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if dimension == "MECHANICAL":
        field, transitions = "mechanical_status", C.MECHANICAL_TRANSITIONS
    else:
        field, transitions = "controls_status", C.CONTROLS_TRANSITIONS

    current = skid[field]
    if to_state not in transitions.get(current, ()):
        fail("ERR_SKID_MILESTONE_OUT_OF_ORDER",
             "%s is not the immediate successor of %s" % (to_state, current))

    skid[field] = to_state

    package = domain.package_of_skid(skid)
    if (dimension == "MECHANICAL" and to_state == "MECH_COMPLETE"
            and package is not None and package["status"] == "REWORK_HOLD"):
        package["status"] = "RELEASED_FOR_FAB"
        db.touch(package)
        project = domain.project_of_package(package)
        if project is not None:
            domain.recompute_posture(project)

    if package is not None:
        domain.refresh_skid_readiness(skid, package)
    db.touch(skid)
    return response.ok(serialize.row(skid))
