"""Design layouts (PRD 3.2, 3.3). Created against a MEASURED project; computes
waste_factor + net_area. Accept gates on product compatibility, retirement, and
at-most-one-accepted, advancing the project MEASURED->DESIGNED."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_enum,
    require_fields,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import (
    get_child_or_404,
    get_project_or_404,
    ref_infill_or_404,
    ref_site_measure_or_404,
    ref_turf_or_404,
)
from middleware import get_auth, require_role
from response import success
from services.calculations import compute_net_area_sqft, compute_waste_factor_pct

bp = Blueprint("design_layouts", __name__)

VARIANTS = {"STANDARD", "PET", "PLAYGROUND", "PUTTING_GREEN"}


def _latest_recorded_measure(project_id):
    rows = [
        m
        for m in db.site_measures.values()
        if m["project_id"] == project_id and m["status"] == "RECORDED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda m: m["_seq"])
    return rows[-1]


@bp.route("/projects/<project_id>/design-layouts", methods=["POST"])
def create_design(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["site_measure_id", "turf_product_id", "infill_product_id", "variant"])

    # Reference existence (priority 5).
    measure = ref_site_measure_or_404(body["site_measure_id"], project_id)
    turf = ref_turf_or_404(body["turf_product_id"])
    infill = ref_infill_or_404(body["infill_product_id"])
    # Well-formedness (priority 6).
    variant = require_enum(body, "variant", VARIANTS)

    waste_factor_pct = compute_waste_factor_pct(
        measure["longest_run_ft"], turf["roll_width_ft"]
    )
    net_area = compute_net_area_sqft(
        measure["gross_area_sqft"], measure["obstruction_area_sqft"], waste_factor_pct
    )

    rec = {
        "project_id": project_id,
        "site_measure_id": measure["id"],
        "turf_product_id": turf["id"],
        "infill_product_id": infill["id"],
        "variant": variant,
        "waste_factor_pct": waste_factor_pct,
        "net_area_sqft": net_area,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.design_layouts[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/design-layouts", methods=["GET"])
def list_designs(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    items = [d for d in db.design_layouts.values() if d["project_id"] == project_id]
    for field, arg in (
        ("site_measure_id", "site_measure_id"),
        ("turf_product_id", "turf_product_id"),
        ("infill_product_id", "infill_product_id"),
        ("status", "status"),
    ):
        val = request.args.get(arg)
        if val is not None:
            items = [d for d in items if d[field] == val]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/design-layouts/<design_layout_id>", methods=["GET"])
def get_design(project_id, design_layout_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    rec = get_child_or_404(db.design_layouts, design_layout_id, project_id, "Design layout")
    return success(public(rec), status=200)


def _variant_product_ok(variant, turf, infill):
    if variant == "PET":
        return turf["pet_approved"] and infill["antimicrobial"]
    if variant == "PLAYGROUND":
        return turf["playground_rated"] and infill["nonabrasive"]
    if variant == "PUTTING_GREEN":
        return turf["putting_rated"]
    return True  # STANDARD has no product-rating requirement.


@bp.route("/projects/<project_id>/design-layouts/<design_layout_id>/accept", methods=["POST"])
def accept_design(project_id, design_layout_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    project = get_project_or_404(project_id)
    design = get_child_or_404(db.design_layouts, design_layout_id, project_id, "Design layout")

    # State (priority 8): only a DRAFT design can be accepted.
    if design["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Design is not in DRAFT status.")

    turf = db.turf_products.get(design["turf_product_id"])
    infill = db.infill_products.get(design["infill_product_id"])

    # Variant/product compatibility (priority 10).
    if not _variant_product_ok(design["variant"], turf, infill):
        raise err(
            "ERR_VARIANT_PRODUCT_MISMATCH",
            "Selected turf/infill not rated for the design variant.",
        )

    # Product availability (priority 11).
    if not turf["active"] or not infill["active"]:
        raise err("ERR_PRODUCT_RETIRED", "Selected turf or infill is retired.")

    # At most one ACCEPTED design per project (priority 12).
    for d in db.design_layouts.values():
        if d["project_id"] == project_id and d["status"] == "ACCEPTED":
            raise err("ERR_DESIGN_ALREADY_ACCEPTED", "Project already has an ACCEPTED design.")

    # Apply transition + project cascade.
    design["status"] = "ACCEPTED"
    touch(design)

    project["variant"] = design["variant"]
    project["billable_area_sqft"] = design["net_area_sqft"]
    if project["workflow_status"] == "MEASURED":
        project["workflow_status"] = "DESIGNED"
    touch(project)

    return success(public(design), status=200)


@bp.route("/projects/<project_id>/design-layouts/<design_layout_id>/reject", methods=["POST"])
def reject_design(project_id, design_layout_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    design = get_child_or_404(db.design_layouts, design_layout_id, project_id, "Design layout")

    if design["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Design is not in DRAFT status.")

    design["status"] = "REJECTED"
    touch(design)
    return success(public(design), status=200)
