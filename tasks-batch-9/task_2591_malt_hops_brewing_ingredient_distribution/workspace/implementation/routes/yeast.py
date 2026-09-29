"""Yeast strains, brewer recipes and the propagation bench."""

from datetime import timedelta

from flask import Blueprint, request

from calc import pitch_advisory
from db import by_created, db, new_entity, now, set_dt, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, require, scope_brewer
from response import array_response, object_response
from serialize import job_out, recipe_out, strain_out
from util import D, whole_days_between
from validation import (
    body,
    f_dec,
    f_dt,
    f_enum,
    f_int,
    f_str,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("yeast", __name__)

LIVE_JOB_STATUSES = ("REQUESTED", "PROPAGATING", "READY")


# ---------------------------------------------------------------------------
# Yeast strains
# ---------------------------------------------------------------------------

@bp.post("/yeast-strains")
def create_strain():
    require(("WarehouseOperator", "PlatformAdmin"))
    payload = body()
    strain_code = f_str(payload, "strain_code", min_len=1, max_len=20)
    name = f_str(payload, "name", min_len=1, max_len=60)
    fermentation_type = f_enum(
        payload, "fermentation_type", ("ALE", "LAGER"), required=True
    )
    lead_time = f_int(
        payload, "propagation_lead_time_days", required=True, minimum=1
    )
    list_price = f_dec(
        payload, "list_price_cents_per_l", required=True, scale=2, exclusive_min=0
    )
    viability = f_dec(
        payload,
        "viability_pct_at_ship",
        required=False,
        scale=2,
        minimum="50.00",
        maximum="100.00",
        default=D("92.0"),
    )
    cells = f_dec(
        payload,
        "cells_per_ml_slurry_billion",
        required=False,
        scale=2,
        exclusive_min=0,
        default=D("1.2"),
    )
    min_batch = f_dec(
        payload, "min_batch_l", required=False, scale=3, exclusive_min=0, default=D("20.0")
    )
    vessel_max = f_dec(
        payload, "vessel_max_l", required=False, scale=3, minimum=0, default=D("2000.0")
    )
    if vessel_max < min_batch:
        raise bad_request("vessel_max_l must be at least min_batch_l")

    for existing in db.strains.values():
        if existing["strain_code"] == strain_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE_CODE", "strain_code is already registered"
            )

    strain = new_entity()
    strain.update(
        {
            "strain_code": strain_code,
            "name": name,
            "fermentation_type": fermentation_type,
            "propagation_lead_time_days": lead_time,
            "viability_pct_at_ship": viability,
            "cells_per_ml_slurry_billion": cells,
            "min_batch_l": min_batch,
            "vessel_max_l": vessel_max,
            "cold_storage_required": True,
            "list_price_cents_per_l": list_price,
        }
    )
    db.strains[strain["id"]] = strain
    return object_response(strain_out(strain), 201)


@bp.get("/yeast-strains/<strain_id>")
def get_strain(strain_id):
    require(ALL_ROLES)
    strain = must_exist("strains", strain_id)
    return object_response(strain_out(strain))


# ---------------------------------------------------------------------------
# Brewer recipes
# ---------------------------------------------------------------------------

@bp.post("/brewer-recipes")
def create_recipe():
    actor = require(("Brewer", "AllocationManager"))
    payload = body()
    brewer_id = f_str(payload, "brewer_id", min_len=1)
    product_id = f_str(payload, "malt_product_id", min_len=1)
    strain_id = f_str(payload, "yeast_strain_id", min_len=1)
    name = f_str(payload, "name", min_len=1, max_len=80)
    batch_volume = f_dec(
        payload, "batch_volume_bbl", required=True, scale=2, exclusive_min=0
    )
    gravity = f_dec(
        payload, "original_gravity_plato", required=True, scale=2, exclusive_min=0
    )
    target_color = f_dec(
        payload, "target_color_lovibond", required=True, scale=2, exclusive_min=0
    )
    target_extract = f_dec(
        payload, "target_extract_pct", required=True, scale=2, exclusive_min=0
    )
    target_protein = f_dec(
        payload, "target_protein_pct", required=True, scale=2, exclusive_min=0
    )
    requested_rate = f_dec(
        payload,
        "requested_pitch_rate_million_cells_per_ml_per_plato",
        required=True,
        scale=3,
        exclusive_min=0,
    )
    adjunct = f_dec(
        payload,
        "adjunct_pct",
        required=False,
        scale=2,
        minimum="0.00",
        maximum="60.00",
        default=D(0),
    )

    scope_brewer(actor, brewer_id)
    must_exist("brewers", brewer_id)
    must_exist("malt_products", product_id)
    must_exist("strains", strain_id)

    recipe = new_entity()
    recipe.update(
        {
            "brewer_id": brewer_id,
            "malt_product_id": product_id,
            "yeast_strain_id": strain_id,
            "name": name,
            "batch_volume_bbl": batch_volume,
            "original_gravity_plato": gravity,
            "adjunct_pct": adjunct,
            "target_color_lovibond": target_color,
            "target_extract_pct": target_extract,
            "target_protein_pct": target_protein,
            "requested_pitch_rate_million_cells_per_ml_per_plato": requested_rate,
        }
    )
    db.recipes[recipe["id"]] = recipe
    return object_response(recipe_out(recipe), 201)


@bp.get("/brewer-recipes/<recipe_id>")
def get_recipe(recipe_id):
    actor = require(ALL_ROLES)
    recipe = must_exist("recipes", recipe_id)
    scope_brewer(actor, recipe["brewer_id"])
    return object_response(recipe_out(recipe))


@bp.get("/brewer-recipes")
def list_recipes():
    actor = require(ALL_ROLES)
    limit, offset = pagination()
    brewer_id = request.args.get("brewer_id")
    product_id = request.args.get("malt_product_id")
    strain_id = request.args.get("yeast_strain_id")
    if brewer_id:
        scope_brewer(actor, brewer_id)
    filter_exists("brewers", brewer_id)
    filter_exists("malt_products", product_id)
    filter_exists("strains", strain_id)

    items = []
    for recipe in db.recipes.values():
        if brewer_id and recipe["brewer_id"] != brewer_id:
            continue
        if product_id and recipe["malt_product_id"] != product_id:
            continue
        if strain_id and recipe["yeast_strain_id"] != strain_id:
            continue
        if actor.is_brewer and recipe["brewer_id"] != actor.user_id:
            continue
        items.append(recipe)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([recipe_out(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Propagation jobs
# ---------------------------------------------------------------------------

def _check_slot(strain, pitch_date, exclude_job_id=None):
    lead_time = int(strain["propagation_lead_time_days"])
    if whole_days_between(now(), pitch_date) < lead_time:
        raise ApiError(
            "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME",
            "pitch_date must be at least the strain's propagation lead time away",
        )
    for other in db.jobs.values():
        if other["id"] == exclude_job_id:
            continue
        if other["yeast_strain_id"] != strain["id"]:
            continue
        if other["status"] not in LIVE_JOB_STATUSES:
            continue
        gap = abs(other["pitch_date"] - pitch_date)
        if gap < timedelta(days=lead_time):
            raise ApiError(
                "ERR_PROPAGATION_SLOT_CONFLICT",
                "Another live job on this strain sits inside the vessel turnover gap",
            )


@bp.post("/yeast-propagation-jobs")
def create_job():
    actor = require(("Brewer", "WarehouseOperator"))
    payload = body()
    brewer_id = f_str(payload, "brewer_id", min_len=1)
    recipe_id = f_str(payload, "recipe_id", min_len=1)
    strain_id = f_str(payload, "yeast_strain_id", min_len=1)
    pitch_date, pitch_raw = f_dt(payload, "pitch_date", required=True)

    scope_brewer(actor, brewer_id)
    brewer = must_exist("brewers", brewer_id)
    recipe = must_exist("recipes", recipe_id)
    strain = must_exist("strains", strain_id)

    if recipe["yeast_strain_id"] != strain_id or recipe["brewer_id"] != brewer_id:
        raise ApiError(
            "ERR_STRAIN_RECIPE_MISMATCH",
            "The recipe's strain and owning brewery must match the request",
        )
    _check_slot(strain, pitch_date)
    if brewer["credit_status"] == "HOLD":
        raise ApiError(
            "ERR_BREWER_CREDIT_HOLD",
            "A brewery on credit hold may not book a propagation",
        )

    job = new_entity()
    job.update(
        {
            "brewer_id": brewer_id,
            "recipe_id": recipe_id,
            "yeast_strain_id": strain_id,
            "replaces_job_id": None,
            "ready_at": None,
            "failure_reason": None,
            "status": "REQUESTED",
        }
    )
    set_dt(job, "pitch_date", pitch_date, pitch_raw)
    job.update(pitch_advisory(recipe, strain, pitch_date))
    db.jobs[job["id"]] = job
    return object_response(job_out(job), 201)


@bp.get("/yeast-propagation-jobs/<job_id>")
def get_job(job_id):
    actor = require(ALL_ROLES)
    job = must_exist("jobs", job_id)
    scope_brewer(actor, job["brewer_id"])
    return object_response(job_out(job))


@bp.get("/yeast-propagation-jobs")
def list_jobs():
    actor = require(ALL_ROLES)
    limit, offset = pagination()
    args = request.args
    brewer_id = args.get("brewer_id")
    recipe_id = args.get("recipe_id")
    strain_id = args.get("yeast_strain_id")
    replaces_id = args.get("replaces_job_id")
    status = args.get("status")
    if brewer_id:
        scope_brewer(actor, brewer_id)
    filter_exists("brewers", brewer_id)
    filter_exists("recipes", recipe_id)
    filter_exists("strains", strain_id)
    filter_exists("jobs", replaces_id)

    items = []
    for job in db.jobs.values():
        if brewer_id and job["brewer_id"] != brewer_id:
            continue
        if recipe_id and job["recipe_id"] != recipe_id:
            continue
        if strain_id and job["yeast_strain_id"] != strain_id:
            continue
        if replaces_id and job["replaces_job_id"] != replaces_id:
            continue
        if status and job["status"] != status:
            continue
        if actor.is_brewer and job["brewer_id"] != actor.user_id:
            continue
        items.append(job)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([job_out(j) for j in page], len(items), limit, offset)


@bp.post("/yeast-propagation-jobs/<job_id>/start")
def start_job(job_id):
    require(("WarehouseOperator",))
    body()
    job = must_exist("jobs", job_id)
    if job["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_JOB_STATE", "Only a REQUESTED job may begin propagation"
        )
    strain = db.strains[job["yeast_strain_id"]]
    job["status"] = "PROPAGATING"
    set_dt(
        job,
        "ready_at",
        now() + timedelta(days=int(strain["propagation_lead_time_days"])),
    )
    touch(job)
    return object_response(job_out(job))


@bp.post("/yeast-propagation-jobs/<job_id>/complete")
def complete_job(job_id):
    require(("WarehouseOperator",))
    payload = body()
    outcome = f_enum(payload, "outcome", ("READY", "FAILED"), required=True)
    failure_reason = f_str(payload, "failure_reason", required=False, max_len=1000)

    job = must_exist("jobs", job_id)
    if job["status"] != "PROPAGATING":
        raise ApiError(
            "ERR_INVALID_JOB_STATE", "Only a PROPAGATING job may be closed out"
        )
    if outcome == "READY":
        job["status"] = "READY"
        job["failure_reason"] = None
    else:
        job["status"] = "FAILED"
        job["failure_reason"] = failure_reason
    touch(job)
    return object_response(job_out(job))


@bp.post("/yeast-propagation-jobs/<job_id>/requeue")
def requeue_job(job_id):
    require(("WarehouseOperator",))
    payload = body()
    pitch_date, pitch_raw = f_dt(payload, "new_pitch_date", required=True)

    job = must_exist("jobs", job_id)
    if job["status"] != "FAILED":
        raise ApiError("ERR_INVALID_JOB_STATE", "Only a FAILED job may be re-booked")
    strain = db.strains[job["yeast_strain_id"]]
    recipe = db.recipes[job["recipe_id"]]
    _check_slot(strain, pitch_date, exclude_job_id=job["id"])

    job["status"] = "REQUESTED"
    job["failure_reason"] = None
    job["ready_at"] = None
    set_dt(job, "pitch_date", pitch_date, pitch_raw)
    job.update(pitch_advisory(recipe, strain, pitch_date))
    touch(job)
    return object_response(job_out(job))
