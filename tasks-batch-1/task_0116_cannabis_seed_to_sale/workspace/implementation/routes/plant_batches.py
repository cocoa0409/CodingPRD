"""PlantBatch endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (get_json_body, require_fields, is_int, paginate,
                     sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import plant_batch_view, waste_event_view

bp = Blueprint("plant_batches", __name__)

READ_ROLES = ["Cultivator", "ComplianceManager", "StateRegulator", "InventoryAuditor"]


def get_batch_or_404(batch_id):
    b = db.plant_batches.get(batch_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "PlantBatch not found.")
    return b


@bp.route("/compliance/plant-batches", methods=["POST"])
@require_auth(["Cultivator"])
def create_plant_batch():
    body = get_json_body()
    require_fields(body, ["license_id", "lot_tag", "strain", "plant_count", "planted_at"])

    license_id = body["license_id"]
    lot_tag = body["lot_tag"]
    strain = body["strain"]
    plant_count = body["plant_count"]
    planted_at = body["planted_at"]

    if not isinstance(lot_tag, str) or not lot_tag:
        raise err("ERR_INVALID_REQUEST", "lot_tag must be a non-empty string.")
    if not is_int(plant_count) or plant_count < 1:
        raise err("ERR_INVALID_REQUEST", "plant_count must be an integer >= 1.")

    # Existence: license FK (priority 3) before business constraints.
    lic = db.licenses.get(license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "License not found.")

    # License-type gating (priority 6): only CULTIVATION hosts plant batches.
    if lic["license_type"] != "CULTIVATION":
        raise err("ERR_LICENSE_TYPE_MISMATCH", "Plant batches require a CULTIVATION license.")

    # Tag uniqueness (priority 10).
    for b in db.plant_batches.values():
        if b["lot_tag"] == lot_tag:
            raise err("ERR_DUPLICATE_TAG", "lot_tag already exists.")

    rec = {
        "id": db.new_id(),
        "license_id": license_id,
        "lot_tag": lot_tag,
        "strain": strain,
        "status": "IMMATURE",
        "plant_count": plant_count,
        "live_plant_count": plant_count,
        "planted_at": planted_at,
    }
    stamp_create(rec)
    db.plant_batches[rec["id"]] = rec
    return object_response(plant_batch_view(rec), 201)


@bp.route("/compliance/plant-batches", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_plant_batches():
    items = list(db.plant_batches.values())
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([plant_batch_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/plant-batches/<batch_id>", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def get_plant_batch(batch_id):
    return object_response(plant_batch_view(get_batch_or_404(batch_id)))


@bp.route("/compliance/plant-batches/<batch_id>/advance", methods=["POST"])
@require_auth(["Cultivator"])
def advance_plant_batch(batch_id):
    batch = get_batch_or_404(batch_id)

    # State (priority 4): must be a legal predecessor stage.
    nxt = {"IMMATURE": "VEGETATIVE", "VEGETATIVE": "FLOWERING"}
    if batch["status"] not in nxt:
        raise err("ERR_INVALID_STATE", "Batch cannot advance from its current state.")

    # License-active (priority 5).
    lic = db.licenses.get(batch["license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Owning license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Owning license is not ACTIVE.")

    # At least one live plant.
    if batch["live_plant_count"] < 1:
        raise err("ERR_INVALID_STATE", "Batch has no live plants to advance.")

    batch["status"] = nxt[batch["status"]]
    touch(batch)
    return object_response(plant_batch_view(batch))


@bp.route("/compliance/plant-batches/<batch_id>/waste-events", methods=["GET"])
@require_auth(["Cultivator", "ComplianceManager", "InventoryAuditor", "StateRegulator"], open_read=True)
def list_batch_waste_events(batch_id):
    get_batch_or_404(batch_id)
    items = [w for w in db.waste_events.values() if w.get("plant_batch_id") == batch_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([waste_event_view(r) for r in page], limit, offset, total)
