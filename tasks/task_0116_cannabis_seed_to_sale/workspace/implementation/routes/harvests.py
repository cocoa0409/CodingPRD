"""Harvest endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, round2,
                     paginate, sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import harvest_view

bp = Blueprint("harvests", __name__)

READ_ROLES = ["Cultivator", "ComplianceManager", "StateRegulator", "InventoryAuditor"]


def get_harvest_or_404(harvest_id):
    h = db.harvests.get(harvest_id)
    if h is None:
        raise err("ERR_NOT_FOUND", "Harvest not found.")
    return h


@bp.route("/compliance/harvests", methods=["POST"])
@require_auth(["Cultivator"])
def create_harvest():
    body = get_json_body()
    require_fields(body, ["plant_batch_id", "harvest_name", "wet_weight_grams"])

    plant_batch_id = body["plant_batch_id"]
    harvest_name = body["harvest_name"]
    wet = body["wet_weight_grams"]

    if not is_number(wet) or wet <= 0:
        raise err("ERR_INVALID_REQUEST", "wet_weight_grams must be > 0.")

    # Existence: source batch (priority 3).
    batch = db.plant_batches.get(plant_batch_id)
    if batch is None:
        raise err("ERR_NOT_FOUND", "PlantBatch not found.")

    # State (priority 4): batch must be FLOWERING.
    if batch["status"] != "FLOWERING":
        raise err("ERR_INVALID_STATE", "Source batch must be FLOWERING to harvest.")

    # License-active (priority 5).
    lic = db.licenses.get(batch["license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Owning license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Owning license is not ACTIVE.")

    # At least one live plant.
    if batch["live_plant_count"] < 1:
        raise err("ERR_INVALID_STATE", "Batch has no live plants to harvest.")

    rec = {
        "id": db.new_id(),
        "plant_batch_id": plant_batch_id,
        "license_id": batch["license_id"],  # copied at harvest time
        "harvest_name": harvest_name,
        "status": "DRYING",
        "wet_weight_grams": wet,
        "dry_weight_grams": None,
        "packaged_weight_grams": 0,
        "remaining_weight_grams": None,
    }
    stamp_create(rec)
    db.harvests[rec["id"]] = rec

    # Cascade: source batch FLOWERING -> HARVESTED, version++.
    batch["status"] = "HARVESTED"
    touch(batch)

    return object_response(harvest_view(rec), 201)


@bp.route("/compliance/harvests", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_harvests():
    items = list(db.harvests.values())
    plant_batch_id = request.args.get("plant_batch_id")
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    if plant_batch_id is not None:
        items = [r for r in items if r["plant_batch_id"] == plant_batch_id]
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([harvest_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/harvests/<harvest_id>", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def get_harvest(harvest_id):
    return object_response(harvest_view(get_harvest_or_404(harvest_id)))


@bp.route("/compliance/harvests/<harvest_id>/cure", methods=["POST"])
@require_auth(["Cultivator"])
def cure_harvest(harvest_id):
    harvest = get_harvest_or_404(harvest_id)
    body = get_json_body()
    require_fields(body, ["dry_weight_grams"])
    dry = body["dry_weight_grams"]
    if not is_number(dry) or dry <= 0:
        raise err("ERR_INVALID_REQUEST", "dry_weight_grams must be > 0.")

    # State (priority 4): must be DRYING.
    if harvest["status"] != "DRYING":
        raise err("ERR_INVALID_STATE", "Harvest must be DRYING to cure.")

    # License-active (priority 5).
    lic = db.licenses.get(harvest["license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Owning license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Owning license is not ACTIVE.")

    # Weight range (priority 19): dry must not exceed wet.
    if dry > harvest["wet_weight_grams"]:
        raise err("ERR_WEIGHT_RANGE", "dry_weight_grams cannot exceed wet_weight_grams.")

    harvest["dry_weight_grams"] = dry
    harvest["status"] = "CURED"
    # remaining = dry - packaged (packaged is 0 at this point typically).
    packaged = harvest.get("packaged_weight_grams") or 0
    from decimal import Decimal
    harvest["remaining_weight_grams"] = round2(Decimal(str(dry)) - Decimal(str(packaged)))
    touch(harvest)
    return object_response(harvest_view(harvest))


@bp.route("/compliance/harvests/<harvest_id>/finish", methods=["POST"])
@require_auth(["Cultivator"])
def finish_harvest(harvest_id):
    harvest = get_harvest_or_404(harvest_id)

    # State (priority 4): must be CURED.
    if harvest["status"] != "CURED":
        raise err("ERR_INVALID_STATE", "Harvest must be CURED to finish.")

    # License-active (priority 5).
    lic = db.licenses.get(harvest["license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Owning license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Owning license is not ACTIVE.")

    # remaining must be packaged down to exactly 0, and >= 1 package.
    rem = harvest.get("remaining_weight_grams")
    if rem != 0 and rem != 0.0:
        raise err("ERR_INVALID_STATE", "Harvest remaining_weight_grams must be 0 to finish.")
    pkgs = [p for p in db.packages.values() if p["harvest_id"] == harvest["id"]]
    if len(pkgs) < 1:
        raise err("ERR_INVALID_STATE", "Harvest must have at least one package to finish.")

    harvest["status"] = "FINISHED"
    touch(harvest)
    return object_response(harvest_view(harvest))
