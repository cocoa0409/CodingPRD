"""WasteEvent endpoints (PRD §3.8). Polymorphic source (PLANT_BATCH|PACKAGE);
package FAILED_TEST full destroy drives the depth-3 cascade (§3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, is_int, round2,
                     paginate, sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import waste_event_view
from services import maybe_auto_finish_harvest

bp = Blueprint("waste_events", __name__)

READ_ROLES = ["Cultivator", "ComplianceManager", "InventoryAuditor", "StateRegulator"]


@bp.route("/compliance/waste-events", methods=["POST"])
@require_auth(["Cultivator", "ComplianceManager"])
def create_waste_event():
    body = get_json_body()
    require_fields(body, ["source_type", "reason", "destroyed_at"])
    source_type = body["source_type"]
    reason = body["reason"]
    destroyed_at = body["destroyed_at"]

    if source_type not in constants.WASTE_SOURCE_TYPES:
        raise err("ERR_INVALID_REQUEST", "Invalid source_type.")
    if reason not in constants.WASTE_REASONS:
        raise err("ERR_INVALID_REQUEST", "Invalid reason.")

    plant_batch_id = body.get("plant_batch_id")
    package_id = body.get("package_id")
    destroyed_grams = body.get("destroyed_grams", 0)
    destroyed_plant_count = body.get("destroyed_plant_count", 0)
    if destroyed_grams is None:
        destroyed_grams = 0
    if destroyed_plant_count is None:
        destroyed_plant_count = 0

    if not is_number(destroyed_grams) or destroyed_grams < 0:
        raise err("ERR_INVALID_REQUEST", "destroyed_grams must be >= 0.")
    if not is_int(destroyed_plant_count) or destroyed_plant_count < 0:
        raise err("ERR_INVALID_REQUEST", "destroyed_plant_count must be an integer >= 0.")

    # Existence (priority 3): the supplied FK for the discriminator must exist.
    batch = None
    pkg = None
    if source_type == "PLANT_BATCH":
        if plant_batch_id is not None:
            batch = db.plant_batches.get(plant_batch_id)
            if batch is None:
                raise err("ERR_NOT_FOUND", "PlantBatch not found.")
    else:  # PACKAGE
        if package_id is not None:
            pkg = db.packages.get(package_id)
            if pkg is None:
                raise err("ERR_NOT_FOUND", "Package not found.")

    # Source discriminator agreement (priority 9).
    if source_type == "PLANT_BATCH":
        if plant_batch_id is None or package_id is not None:
            raise err("ERR_SOURCE_DISCRIMINATOR_MISMATCH",
                      "PLANT_BATCH requires plant_batch_id and null package_id.")
    else:  # PACKAGE
        if package_id is None or plant_batch_id is not None:
            raise err("ERR_SOURCE_DISCRIMINATOR_MISMATCH",
                      "PACKAGE requires package_id and null plant_batch_id.")

    if source_type == "PLANT_BATCH":
        return _waste_plant_batch(batch, reason, destroyed_at, destroyed_plant_count,
                                  plant_batch_id)
    return _waste_package(pkg, reason, destroyed_at, destroyed_grams, package_id)


def _waste_plant_batch(batch, reason, destroyed_at, destroyed_plant_count, plant_batch_id):
    # Weight range (priority 19): destroyed_plant_count <= live_plant_count.
    if destroyed_plant_count > batch["live_plant_count"]:
        raise err("ERR_WEIGHT_RANGE", "destroyed_plant_count exceeds live_plant_count.")

    rec = _make_record("PLANT_BATCH", reason, destroyed_at,
                       plant_batch_id=plant_batch_id, package_id=None,
                       destroyed_grams=0, destroyed_plant_count=destroyed_plant_count)

    # Decrement live_plant_count; full destruction terminalizes batch.
    full = destroyed_plant_count == batch["live_plant_count"]
    batch["live_plant_count"] = batch["live_plant_count"] - destroyed_plant_count
    if full:
        batch["status"] = "DESTROYED"
    touch(batch)
    return object_response(waste_event_view(rec), 201)


def _waste_package(pkg, reason, destroyed_at, destroyed_grams, package_id):
    # State tier (priority 18): a FAILED package FAILED_TEST waste must destroy
    # the FULL remaining grams to terminalize; a partial destroy is rejected.
    if pkg["status"] == "FAILED" and reason == "FAILED_TEST":
        if Decimal(str(destroyed_grams)) != Decimal(str(pkg["remaining_grams"])):
            raise err("ERR_PARTIAL_DESTROY_NOT_TERMINAL",
                      "A FAILED_TEST destroy of a FAILED package must consume all remaining grams.")

    # Weight range (priority 19): destroyed_grams <= remaining_grams.
    if Decimal(str(destroyed_grams)) > Decimal(str(pkg["remaining_grams"])):
        raise err("ERR_WEIGHT_RANGE", "destroyed_grams exceeds package remaining_grams.")

    rec = _make_record("PACKAGE", reason, destroyed_at,
                       plant_batch_id=None, package_id=package_id,
                       destroyed_grams=destroyed_grams, destroyed_plant_count=0)

    # Decrement remaining_grams (hop 1).
    new_remaining = round2(Decimal(str(pkg["remaining_grams"])) - Decimal(str(destroyed_grams)))
    pkg["remaining_grams"] = new_remaining

    # Hop 2: full FAILED_TEST destruction of a FAILED package -> DESTROYED.
    terminalized = False
    if (pkg["status"] == "FAILED" and reason == "FAILED_TEST"
            and (new_remaining == 0 or new_remaining == 0.0)):
        pkg["status"] = "DESTROYED"
        terminalized = True
    touch(pkg)

    # Hop 3: bubble-up auto-finish of the source harvest. Harvest yield is NOT
    # re-run on package waste (PRD §3.4).
    if terminalized:
        maybe_auto_finish_harvest(db.harvests.get(pkg["harvest_id"]))

    return object_response(waste_event_view(rec), 201)


def _make_record(source_type, reason, destroyed_at, plant_batch_id, package_id,
                 destroyed_grams, destroyed_plant_count):
    rec = {
        "id": db.new_id(),
        "source_type": source_type,
        "plant_batch_id": plant_batch_id,
        "package_id": package_id,
        "reason": reason,
        "destroyed_grams": destroyed_grams,
        "destroyed_plant_count": destroyed_plant_count,
        "destroyed_at": destroyed_at,
    }
    stamp_create(rec, versioned=False)
    db.waste_events[rec["id"]] = rec
    return rec


@bp.route("/compliance/waste-events", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_waste_events():
    items = list(db.waste_events.values())
    source_type = request.args.get("source_type")
    plant_batch_id = request.args.get("plant_batch_id")
    package_id = request.args.get("package_id")
    reason = request.args.get("reason")
    if source_type is not None:
        items = [r for r in items if r["source_type"] == source_type]
    if plant_batch_id is not None:
        items = [r for r in items if r.get("plant_batch_id") == plant_batch_id]
    if package_id is not None:
        items = [r for r in items if r.get("package_id") == package_id]
    if reason is not None:
        items = [r for r in items if r["reason"] == reason]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([waste_event_view(r) for r in page], limit, offset, total)
