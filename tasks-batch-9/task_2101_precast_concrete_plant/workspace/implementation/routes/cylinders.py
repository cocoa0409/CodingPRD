"""Cylinder sets and breaks (PRD 3.5)."""
from flask import Blueprint

import auth
import calc
import cascade
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("cylinders", __name__)


@bp.post("/bed-runs/<run_id>/cylinder-sets")
def create_cylinder_set(run_id):
    auth.require(constants.ROLE_QC_TECHNICIAN)
    run = lookup.bed_run(run_id)
    body = validation.get_body()
    purpose = validation.req_enum(body, "purpose", constants.CYLINDER_PURPOSES)
    specimen_count = validation.req_int(body, "specimen_count", minimum=2, maximum=6)
    cured_with_member = validation.req_bool(body, "cured_with_member")

    row = db.new_row(db.store.cylinder_sets, {
        "bed_run_id": run["id"],
        "purpose": purpose,
        "specimen_count": specimen_count,
        "cured_with_member": cured_with_member,
        "cast_at": db.store.now_iso(),
        "status": "CAST",
        "raw_mean_psi": None,
        "qualified_strength_psi": None,
        "strength_variant": None,
        "recorded_by_user_ids": [],
    })
    db.mark_fresh(row)
    return response.object_response(serialize.cylinder_set(row), 201)


@bp.get("/bed-runs/<run_id>/cylinder-sets")
def list_run_cylinder_sets(run_id):
    auth.require_any()
    lookup.bed_run(run_id)
    purpose = validation.query_filter("purpose")
    rows = [s for s in db.store.cylinder_sets.values()
            if s["bed_run_id"] == run_id
            and (purpose is None or s["purpose"] == purpose)]
    return listing.list_response(rows, serialize.cylinder_set)


@bp.get("/cylinder-sets/<set_id>")
def get_cylinder_set(set_id):
    auth.require_any()
    row = lookup.cylinder_set(set_id)
    return response.object_response(serialize.cylinder_set(row), 200)


@bp.post("/cylinder-sets/<set_id>/breaks")
def record_break(set_id):
    user_id, _role = auth.require(constants.ROLE_QC_TECHNICIAN)
    cylinder_set = lookup.cylinder_set(set_id)
    body = validation.get_body()
    load_lbf = validation.req_number(body, "load_lbf", exclusive_min=0)
    diameter = validation.req_decimal_choice(body, "diameter_in",
                                             constants.CYLINDER_DIAMETERS)

    run = db.store.bed_runs[cylinder_set["bed_run_id"]]
    if run["status"] == "STRIPPED":
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "The owning bed run has already been stripped.")

    recorded, _valid = calc.cylinder_set_counts(cylinder_set)
    if recorded >= cylinder_set["specimen_count"]:
        errors.fail(errors.ERR_SPECIMEN_LIMIT_REACHED,
                    "Every specimen of this set has already been broken.")

    break_at = db.store.now()
    cast_at = db.parse_iso8601(cylinder_set["cast_at"])
    row = db.new_row(db.store.cylinder_breaks, {
        "cylinder_set_id": cylinder_set["id"],
        "break_at": db.iso_millis(break_at),
        "age_hours": calc.age_hours(break_at, cast_at),
        "load_lbf": load_lbf,
        "diameter_in": diameter,
        "computed_psi": calc.computed_psi(load_lbf, diameter),
        "inclusion_status": "VALID",
        "recorded_by_user_id": user_id,
    })
    db.mark_fresh(row)

    if user_id not in cylinder_set["recorded_by_user_ids"]:
        cylinder_set["recorded_by_user_ids"].append(user_id)

    cascade.recompute_set_after_break(cylinder_set, run)
    return response.object_response(serialize.cylinder_break(row), 201)


@bp.get("/cylinder-sets/<set_id>/breaks")
def list_breaks(set_id):
    auth.require_any()
    lookup.cylinder_set(set_id)
    rows = [b for b in db.store.cylinder_breaks.values()
            if b["cylinder_set_id"] == set_id]
    return listing.list_response(rows, serialize.cylinder_break)
