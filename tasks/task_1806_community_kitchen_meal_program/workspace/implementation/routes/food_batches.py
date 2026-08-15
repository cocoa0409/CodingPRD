"""FoodBatch receiving and the inspection cycle (PRD 3.3)."""
from flask import Blueprint, request

from db import db, inspection_rounds
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_BATCH_EXPIRED,
    ERR_REFERENCE_INVALID, ERR_SAFETY_VIOLATION,
)
from helpers import (
    get_body, req_field, req_int, req_enum, opt_list, opt_num, check_enum_subset,
    stamp_new, paginate, apply_filters, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list
from services import core
from util import parse_datetime, fmt_datetime, CLOCK

bp = Blueprint("food_batches", __name__)

ALLERGENS = {"GLUTEN", "DAIRY", "EGG", "SOY", "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME"}
SOURCE_TYPES = {"DONATION", "PURCHASE", "RESCUE"}
FSO = ["FoodSafetyOfficer"]


def _batch_view(b):
    out = public(b)
    out.pop("_use_by", None)
    return out


@bp.route("/kitchen/food-batches", methods=["POST"])
def create_batch():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["KitchenManager", "FoodSafetyOfficer"])

    site_id = req_field(body, "site_id", str)
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    item_description = req_field(body, "item_description", str)
    quantity_servings = req_int(body, "quantity_servings", minimum=1)
    received_at = req_field(body, "received_at", str)
    use_by = req_field(body, "use_by", str)
    allergen_tags = opt_list(body, "allergen_tags", [])
    check_enum_subset(allergen_tags, ALLERGENS, "allergen_tags")
    unit_cost = opt_num(body, "unit_cost_cents_per_serving", None)

    try:
        rec_at = parse_datetime(received_at)
        use_by_dt = parse_datetime(use_by)
    except ValueError:
        raise_error(ERR_VALIDATION, "received_at and use_by must be ISO datetimes")

    if source_type == "PURCHASE" and unit_cost is None:
        raise_error(ERR_VALIDATION,
                    "unit_cost_cents_per_serving is required for PURCHASE batches")

    site = db["sites"].get(site_id)
    if site is None:
        raise_error(ERR_REFERENCE_INVALID, f"site not found: {site_id}")

    rec = stamp_new({
        "site_id": site_id,
        "source_type": source_type,
        "item_description": item_description,
        "quantity_servings": quantity_servings,
        "remaining_servings": quantity_servings,
        "received_at": fmt_datetime(rec_at),
        "use_by": fmt_datetime(use_by_dt),
        "_use_by": use_by_dt,
        "unit_cost_cents_per_serving": unit_cost if source_type == "PURCHASE" else 0,
        "inspection_result": "PENDING",
        "allergen_tags": allergen_tags,
        "status": "RECEIVED",
    })
    db["food_batches"][rec["id"]] = rec
    inspection_rounds[rec["id"]] = 0
    return success_object(_batch_view(rec), 201)


@bp.route("/kitchen/food-batches/<bid>", methods=["GET"])
def get_batch(bid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    rec = get_or_404("food_batches", bid)
    return success_object(_batch_view(rec))


@bp.route("/kitchen/food-batches/<bid>/batch-allocations", methods=["GET"])
def list_batch_allocations(bid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    get_or_404("food_batches", bid)
    items = [a for a in db["batch_allocations"].values()
             if a["food_batch_id"] == bid and not a.get("released")]
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/food-batches/<bid>/waste-logs", methods=["GET"])
def list_batch_waste(bid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    get_or_404("food_batches", bid)
    items = [w for w in db["waste_logs"].values() if w["food_batch_id"] == bid]
    items = apply_filters(items, request.args, ["reason", "disposition"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/food-batches/<bid>/begin-inspection", methods=["POST"])
def begin_inspection(bid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, FSO)
    batch = get_or_404("food_batches", bid)

    if batch["status"] not in ("RECEIVED", "QUARANTINED", "ACCEPTED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot begin inspection from {batch['status']}")
    if not core.batch_not_expired(batch):
        raise_error(ERR_BATCH_EXPIRED, "batch is expired (now >= use_by)")

    if batch["status"] == "QUARANTINED":
        if not core.safety_discard_exists(bid):
            raise_error(ERR_INVALID_STATE,
                        "a SAFETY_DISCARD WasteLog must be recorded before re-inspection")
        inspection_rounds[bid] = inspection_rounds.get(bid, 0) + 1
    elif batch["status"] == "ACCEPTED":
        batch["inspection_result"] = "PENDING"

    batch["status"] = "INSPECTING"
    touch(batch)
    return success_object(_batch_view(batch))


@bp.route("/kitchen/food-batches/<bid>/record-inspection", methods=["POST"])
def record_inspection(bid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, FSO)
    batch = get_or_404("food_batches", bid)

    result = req_enum(body, "result", {"PASSED", "FAILED"})

    if batch["status"] != "INSPECTING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot record inspection from {batch['status']}")

    if result == "PASSED":
        if not core.batch_not_expired(batch):
            raise_error(ERR_BATCH_EXPIRED, "batch is expired (now >= use_by)")
        batch["inspection_result"] = "PASSED"
        batch["status"] = "ACCEPTED"
        core.recalc_batch_remaining(batch)
    else:
        batch["inspection_result"] = "FAILED"
        batch["status"] = "QUARANTINED"
        touch(batch)
        core.quarantine_cascade(batch)
    return success_object(_batch_view(batch))


@bp.route("/kitchen/food-batches/<bid>/reject", methods=["POST"])
def reject_batch(bid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, FSO)
    batch = get_or_404("food_batches", bid)

    if batch["status"] != "QUARANTINED":
        raise_error(ERR_INVALID_STATE, f"cannot reject from {batch['status']}")

    core.release_batch_allocations(batch)
    batch["remaining_servings"] = 0
    batch["status"] = "REJECTED"
    touch(batch)
    return success_object(_batch_view(batch))
