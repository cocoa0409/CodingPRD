"""FoamBatch endpoints: pour, cure cycle, quarantine, scrap."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_number, as_string, body, require
from services import calc, cascade

bp = Blueprint("foam_batches", __name__)

DENSITY_CLASSES = {"STANDARD", "HIGH_DENSITY", "MEMORY"}


def batch_view(b):
    return {
        "id": b["id"],
        "foam_density_class": b["foam_density_class"],
        "poured_mass_kg": b["poured_mass_kg"],
        "available_mass_kg": b["available_mass_kg"],
        "reserved_mass_kg": b["reserved_mass_kg"],
        "consumed_mass_kg": b["consumed_mass_kg"],
        "scrapped_mass_kg": b["scrapped_mass_kg"],
        "chamber_id": b["chamber_id"],
        "cure_started_at": b["cure_started_at"],
        "cure_eligible_at": b["cure_eligible_at"],
        "cure_cycles": b["cure_cycles"],
        "poured_by_user_id": b["poured_by_user_id"],
        "certified_by_user_id": b["certified_by_user_id"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def get_batch(batch_id):
    b = db.foam_batches.get(batch_id)
    if b is None:
        errors.raise_err(errors.ERR_FOAM_BATCH_NOT_FOUND, "foam batch not found")
    return b


@bp.route("/foam-batches", methods=["POST"])
def pour_batch():
    user_id, _ = middleware.require_roles(["LineSupervisor"])
    data = body()
    density = as_enum(require(data, "foam_density_class"), "foam_density_class", DENSITY_CLASSES)
    mass = as_number(require(data, "poured_mass_kg"), "poured_mass_kg")
    if calc.dec(mass) <= 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "poured_mass_kg must be > 0")
    chamber = as_string(require(data, "chamber_id"), "chamber_id")
    batch = {
        "id": db.new_id(),
        "foam_density_class": density,
        "poured_mass_kg": mass,
        "available_mass_kg": mass,
        "reserved_mass_kg": 0,
        "consumed_mass_kg": 0,
        "scrapped_mass_kg": 0,
        "chamber_id": chamber,
        "cure_started_at": None,
        "cure_eligible_at": None,
        "cure_cycles": 0,
        "poured_by_user_id": user_id,
        "certified_by_user_id": None,
        "status": "POURED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.foam_batches, batch)
    return response.success_object(batch_view(batch), 201)


@bp.route("/foam-batches", methods=["GET"])
def list_batches():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.foam_batches.values())
    q = request.args.get("status")
    if q is not None:
        items = [b for b in items if b["status"] == q]
    q = request.args.get("chamber_id")
    if q is not None:
        items = [b for b in items if b["chamber_id"] == q]
    items.sort(key=lambda b: b["_seq"])
    return response.success_list([batch_view(b) for b in items])


@bp.route("/foam-batches/<batchId>", methods=["GET"])
def get_one_batch(batchId):
    middleware.require_roles(middleware.ALL_ROLES)
    b = get_batch(batchId)
    return response.success_object(batch_view(b))


@bp.route("/foam-batches/<batchId>/start-cure", methods=["POST"])
def start_cure(batchId):
    middleware.require_roles(["LineSupervisor"])
    batch = get_batch(batchId)
    data = body()
    ambient = as_number(require(data, "ambient_temp_c"), "ambient_temp_c")
    # tier 5
    if batch["status"] != "POURED":
        errors.raise_err(errors.ERR_BATCH_NOT_POURED, "batch must be POURED")
    now = clock.now()
    total_hours = calc.BASE_CURE_HOURS[batch["foam_density_class"]] + calc.cure_adjust_hours(ambient)
    new_start = now
    new_end = now + timedelta(hours=total_hours)
    # tier 8: chamber aggregate capacity
    if calc.chamber_over_capacity(batch, new_start, new_end, now):
        errors.raise_err(
            errors.ERR_CHAMBER_CAPACITY_EXCEEDED,
            "chamber capacity exceeded",
        )
    batch["cure_started_at"] = clock.iso_fmt(now)
    batch["cure_eligible_at"] = clock.iso_fmt(new_end)
    batch["cure_cycles"] += 1
    batch["status"] = "CURING"
    cascade.bump(batch)
    return response.success_object(batch_view(batch))


@bp.route("/foam-batches/<batchId>/certify-cured", methods=["POST"])
def certify_cured(batchId):
    user_id, _ = middleware.require_roles(["QcInspector"])
    batch = get_batch(batchId)
    # tier 5
    if batch["status"] != "CURING":
        errors.raise_err(errors.ERR_BATCH_NOT_CURING, "batch must be CURING")
    # tier 6: clock >= cure_eligible_at (inclusive boundary)
    now = clock.now()
    eligible = clock.iso_parse(batch["cure_eligible_at"])
    if now < eligible:
        errors.raise_err(errors.ERR_CURE_INCOMPLETE, "cure not complete")
    # tier 7: segregation of duties
    if user_id == batch["poured_by_user_id"]:
        errors.raise_err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "cure certifier must differ from pourer",
        )
    batch["status"] = "CURED"
    batch["certified_by_user_id"] = user_id
    cascade.bump(batch)
    return response.success_object(batch_view(batch))


@bp.route("/foam-batches/<batchId>/quarantine", methods=["POST"])
def quarantine(batchId):
    middleware.require_roles(["QcInspector"])
    batch = get_batch(batchId)
    if batch["status"] != "CURING":
        errors.raise_err(errors.ERR_BATCH_NOT_CURING, "batch must be CURING")
    batch["status"] = "QUARANTINED"
    cascade.bump(batch)
    return response.success_object(batch_view(batch))


@bp.route("/foam-batches/<batchId>/release-to-cure", methods=["POST"])
def release_to_cure(batchId):
    middleware.require_roles(["LineSupervisor"])
    batch = get_batch(batchId)
    if batch["status"] != "QUARANTINED":
        errors.raise_err(errors.ERR_BATCH_NOT_QUARANTINED, "batch must be QUARANTINED")
    batch["cure_cycles"] += 1
    eligible = clock.iso_parse(batch["cure_eligible_at"])
    batch["cure_eligible_at"] = clock.iso_fmt(
        eligible + timedelta(hours=calc.RECURE_PENALTY_HOURS)
    )
    batch["status"] = "CURING"
    cascade.bump(batch)
    return response.success_object(batch_view(batch))


@bp.route("/foam-batches/<batchId>/scrap", methods=["POST"])
def scrap(batchId):
    middleware.require_roles(["QcInspector"])
    batch = get_batch(batchId)
    if batch["status"] != "QUARANTINED":
        errors.raise_err(errors.ERR_BATCH_NOT_QUARANTINED, "batch must be QUARANTINED")
    batch["scrapped_mass_kg"] = batch["available_mass_kg"]
    batch["available_mass_kg"] = 0
    batch["status"] = "SCRAPPED"
    cascade.bump(batch)
    return response.success_object(batch_view(batch))
