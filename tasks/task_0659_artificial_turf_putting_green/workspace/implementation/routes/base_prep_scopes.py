"""Base prep & drainage scopes (PRD 3.4). Created against a design; computes
drainage_tier + costs. Finalize freezes costs and requires the design ACCEPTED."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_number_gt,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_child_or_404, get_project_or_404, ref_design_or_404
from middleware import get_auth, require_role
from response import success
from services.calculations import compute_base_prep_costs, compute_drainage_tier

bp = Blueprint("base_prep_scopes", __name__)


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


@bp.route("/projects/<project_id>/base-prep-scopes", methods=["POST"])
def create_scope(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["design_layout_id", "base_depth_in"])
    design = ref_design_or_404(body["design_layout_id"], project_id)
    base_depth_in = require_number_gt(body, "base_depth_in", 0)

    measure = _latest_recorded_measure(project_id)
    slope_pct = measure["slope_pct"] if measure is not None else 0
    soil_drains_freely = (
        measure["soil_drains_freely"] if measure is not None else True
    )

    drainage_tier = compute_drainage_tier(slope_pct, soil_drains_freely, design["variant"])
    excavation, drainage = compute_base_prep_costs(
        design["net_area_sqft"], base_depth_in, drainage_tier
    )

    rec = {
        "project_id": project_id,
        "design_layout_id": design["id"],
        "base_depth_in": base_depth_in,
        "drainage_tier": drainage_tier,
        "excavation_cost_cents": excavation,
        "drainage_cost_cents": drainage,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.base_prep_scopes[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/base-prep-scopes", methods=["GET"])
def list_scopes(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    items = [s for s in db.base_prep_scopes.values() if s["project_id"] == project_id]
    for field in ("design_layout_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s[field] == val]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/base-prep-scopes/<base_prep_scope_id>", methods=["GET"])
def get_scope(project_id, base_prep_scope_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    rec = get_child_or_404(db.base_prep_scopes, base_prep_scope_id, project_id, "Base prep scope")
    return success(public(rec), status=200)


@bp.route(
    "/projects/<project_id>/base-prep-scopes/<base_prep_scope_id>/finalize",
    methods=["POST"],
)
def finalize_scope(project_id, base_prep_scope_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    scope = get_child_or_404(
        db.base_prep_scopes, base_prep_scope_id, project_id, "Base prep scope"
    )

    if scope["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Base prep scope is not in DRAFT status.")

    design = db.design_layouts.get(scope["design_layout_id"])
    if design is None or design["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Referenced design layout is not ACCEPTED.")

    # Freeze costs at finalize time (recompute against current accepted design).
    measure = _latest_recorded_measure(project_id)
    slope_pct = measure["slope_pct"] if measure is not None else 0
    soil_drains_freely = measure["soil_drains_freely"] if measure is not None else True
    drainage_tier = compute_drainage_tier(slope_pct, soil_drains_freely, design["variant"])
    excavation, drainage = compute_base_prep_costs(
        design["net_area_sqft"], scope["base_depth_in"], drainage_tier
    )
    scope["drainage_tier"] = drainage_tier
    scope["excavation_cost_cents"] = excavation
    scope["drainage_cost_cents"] = drainage

    scope["status"] = "FINALIZED"
    touch(scope)
    return success(public(scope), status=200)
