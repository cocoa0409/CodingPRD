"""§3.1 OpticalDesign and ToleranceAllocation routes."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, filt, get_body, occ, ok, ok_list,
                    pagination, path_row, v_enum, v_int, v_num, v_str)
from errors import ApiError
from store import ordered, store

bp = Blueprint("designs", __name__)

TOLERANCE_METHODS = ["STATISTICAL", "WORST_CASE"]
CONTRIBUTOR_TYPES = [
    "SURFACE_IRREGULARITY", "INDEX_HOMOGENEITY", "STRIAE", "WEDGE_ANGLE",
    "CENTER_THICKNESS", "COATING_STRESS", "MOUNT_STRAIN",
]

SPEC_FIELDS = [
    "design_code", "aperture_mm", "wavelength_min_nm", "wavelength_max_nm",
    "required_rms_wavefront_waves", "tolerance_budget_waves",
    "transmitted_wavefront_budget_waves", "surface_figure_budget_waves",
    "surface_roughness_budget_nm", "min_center_thickness_um",
    "min_index_homogeneity_grade", "max_striae_grade",
    "scratch_dig_scratch_limit", "scratch_dig_dig_limit",
    "cleanliness_limit_per_cm2", "tolerance_method",
]


def _duplicate_design_code(code, skip_id=None):
    for row in store.designs.values():
        if row["design_code"] == code and row["id"] != skip_id:
            return True
    return False


def _new_design(spec):
    row = store.new_row()
    for name in SPEC_FIELDS:
        row[name] = spec[name]
    row["design_status"] = "DRAFT"
    row["rss_stack_waves"] = None
    row["worst_case_stack_waves"] = None
    row["governing_stack_waves"] = None
    row["allocated_tolerance_waves"] = None
    row["tolerance_verdict"] = "PENDING"
    row["design_revision"] = 1
    row["supersedes_design_id"] = None
    return row


@bp.post("/optics/optical-designs")
def create_design():
    authenticate(["OpticsEngineer"])
    body = get_body()

    spec = {}
    spec["design_code"] = v_str(body, "design_code", True, min_len=1, max_len=40)
    spec["aperture_mm"] = v_num(body, "aperture_mm", True, gt=0)
    spec["wavelength_min_nm"] = v_int(body, "wavelength_min_nm", True, ge=200)
    spec["wavelength_max_nm"] = v_int(body, "wavelength_max_nm", True, le=20000)
    if spec["wavelength_max_nm"] <= spec["wavelength_min_nm"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "wavelength_max_nm must be greater than wavelength_min_nm.")
    spec["required_rms_wavefront_waves"] = v_num(
        body, "required_rms_wavefront_waves", True, gt=0)
    spec["tolerance_budget_waves"] = v_num(body, "tolerance_budget_waves", True, gt=0)
    spec["transmitted_wavefront_budget_waves"] = v_num(
        body, "transmitted_wavefront_budget_waves", True, gt=0)
    spec["surface_figure_budget_waves"] = v_num(
        body, "surface_figure_budget_waves", False, Decimal("0.0250"), gt=0)
    spec["surface_roughness_budget_nm"] = v_num(
        body, "surface_roughness_budget_nm", False, Decimal("1.2000"), gt=0)
    spec["min_center_thickness_um"] = v_num(
        body, "min_center_thickness_um", False, Decimal("5800.0"), gt=0)
    spec["min_index_homogeneity_grade"] = v_enum(
        body, "min_index_homogeneity_grade", calc.INDEX_HOMOGENEITY_GRADES, False, "H3")
    spec["max_striae_grade"] = v_enum(
        body, "max_striae_grade", calc.STRIAE_GRADES, False, "B")
    spec["scratch_dig_scratch_limit"] = v_int(
        body, "scratch_dig_scratch_limit", False, 40, ge=0)
    spec["scratch_dig_dig_limit"] = v_int(body, "scratch_dig_dig_limit", False, 20, ge=0)
    spec["cleanliness_limit_per_cm2"] = v_int(
        body, "cleanliness_limit_per_cm2", False, 50, ge=0)
    spec["tolerance_method"] = v_enum(
        body, "tolerance_method", TOLERANCE_METHODS, False, "STATISTICAL")

    if _duplicate_design_code(spec["design_code"]):
        raise ApiError("ERR_DUPLICATE_DESIGN_CODE")

    row = _new_design(spec)
    store.designs[row["id"]] = row
    return ok(logic.ser_design(row), 201)


@bp.get("/optics/optical-designs/<row_id>")
def get_design(row_id):
    authenticate(ALL_ROLES)
    row = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    return ok(logic.ser_design(row))


@bp.get("/optics/optical-designs")
def list_designs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.designs.values()))
    for name in ("supersedes_design_id", "design_status", "tolerance_verdict"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_design, limit, offset)


@bp.post("/optics/optical-designs/<row_id>/tolerance-allocations")
def create_allocation(row_id):
    authenticate(["OpticsEngineer"])
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    body = get_body()

    contributor_type = v_enum(body, "contributor_type", CONTRIBUTOR_TYPES, True)
    sensitivity = v_num(body, "sensitivity_waves_per_unit", True, gt=0)
    units = v_num(body, "manufacturing_tolerance_units", True, gt=0)

    if design["design_status"] != "DRAFT":
        raise ApiError("ERR_DESIGN_NOT_RELEASED")

    row = store.new_row()
    row["design_id"] = design["id"]
    row["contributor_type"] = contributor_type
    row["sensitivity_waves_per_unit"] = sensitivity
    row["manufacturing_tolerance_units"] = units
    row["contribution_waves"] = calc.contribution_waves(sensitivity, units)
    row["allocation_status"] = "ACTIVE"
    store.allocations[row["id"]] = row
    return ok(logic.ser_allocation(row), 201)


@bp.get("/optics/optical-designs/<row_id>/tolerance-allocations")
def list_design_allocations(row_id):
    authenticate(ALL_ROLES)
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    limit, offset = pagination()
    rows = ordered([a for a in store.allocations.values()
                    if a["design_id"] == design["id"]])
    value = filt("allocation_status")
    if value is not None:
        rows = [r for r in rows if r["allocation_status"] == value]
    return ok_list(rows, logic.ser_allocation, limit, offset)


@bp.get("/optics/tolerance-allocations/<row_id>")
def get_allocation(row_id):
    authenticate(ALL_ROLES)
    row = path_row(store.allocations, row_id, "ERR_TOLERANCE_ALLOCATION_NOT_FOUND")
    return ok(logic.ser_allocation(row))


@bp.post("/optics/tolerance-allocations/<row_id>/retire")
def retire_allocation(row_id):
    authenticate(["OpticsEngineer"])
    row = path_row(store.allocations, row_id, "ERR_TOLERANCE_ALLOCATION_NOT_FOUND")
    if row["allocation_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["allocation_status"] = "RETIRED"
    store.touch(row)
    return ok(logic.ser_allocation(row))


@bp.post("/optics/optical-designs/<row_id>/tolerance-analysis")
def tolerance_analysis(row_id):
    authenticate(["OpticsEngineer"])
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    if design["design_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    active = ordered([a for a in store.allocations.values()
                      if a["design_id"] == design["id"]
                      and a["allocation_status"] == "ACTIVE"])
    if not active:
        raise ApiError("ERR_TOLERANCE_STACK_EMPTY")

    contributions = [Decimal(a["contribution_waves"]) for a in active]
    rss, worst, governing, verdict = calc.tolerance_stack_analysis(
        contributions, design["tolerance_method"], design["tolerance_budget_waves"])
    design["rss_stack_waves"] = rss
    design["worst_case_stack_waves"] = worst
    design["governing_stack_waves"] = governing
    design["allocated_tolerance_waves"] = governing
    design["tolerance_verdict"] = verdict
    design["design_status"] = "TOLERANCED"
    store.touch(design)
    return ok(logic.ser_design(design))


@bp.post("/optics/optical-designs/<row_id>/release")
def release_design(row_id):
    authenticate(["OpticsEngineer", "QualityManager"])
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    if design["design_status"] != "TOLERANCED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if design["tolerance_verdict"] == "FAIL":
        raise ApiError("ERR_TOLERANCE_BUDGET_EXCEEDED")
    design["design_status"] = "RELEASED"
    store.touch(design)
    return ok(logic.ser_design(design))


@bp.post("/optics/optical-designs/<row_id>/revisions")
def create_revision(row_id):
    authenticate(["OpticsEngineer"])
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    body = get_body()

    design_code = v_str(body, "design_code", True, min_len=1, max_len=40)
    tolerance_budget = v_num(body, "tolerance_budget_waves", False, None, gt=0)
    transmitted_budget = v_num(body, "transmitted_wavefront_budget_waves", False,
                               None, gt=0)
    tolerance_method = v_enum(body, "tolerance_method", TOLERANCE_METHODS, False, None)
    required_rms = v_num(body, "required_rms_wavefront_waves", False, None, gt=0)
    aperture = v_num(body, "aperture_mm", False, None, gt=0)

    occ(body, "expected_design_version", design, "ERR_STALE_DESIGN_VERSION")

    if design["design_status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if _duplicate_design_code(design_code):
        raise ApiError("ERR_DUPLICATE_DESIGN_CODE")

    spec = {name: design[name] for name in SPEC_FIELDS}
    spec["design_code"] = design_code
    if tolerance_budget is not None:
        spec["tolerance_budget_waves"] = tolerance_budget
    if transmitted_budget is not None:
        spec["transmitted_wavefront_budget_waves"] = transmitted_budget
    if tolerance_method is not None:
        spec["tolerance_method"] = tolerance_method
    if required_rms is not None:
        spec["required_rms_wavefront_waves"] = required_rms
    if aperture is not None:
        spec["aperture_mm"] = aperture

    row = _new_design(spec)
    row["design_revision"] = int(design["design_revision"]) + 1
    row["supersedes_design_id"] = design["id"]
    store.designs[row["id"]] = row

    design["design_status"] = "SUPERSEDED"
    store.touch(design)

    return ok(logic.ser_design(row), 201)


@bp.get("/optics/optical-designs/<row_id>/export-classifications")
def list_design_classifications(row_id):
    authenticate(ALL_ROLES)
    design = path_row(store.designs, row_id, "ERR_DESIGN_NOT_FOUND")
    limit, offset = pagination()
    rows = ordered([c for c in store.classifications.values()
                    if c["design_id"] == design["id"]])
    value = filt("classification_status")
    if value is not None:
        rows = [r for r in rows if r["classification_status"] == value]
    return ok_list(rows, logic.ser_classification, limit, offset)
