"""SalvageBatch and SalvageItem endpoints (PRD 3.7)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    batch_item_count, bump_program, post_budget, require_active,
    salvage_settlement_value, ser_batch, ser_salvage_item,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, opt_bool, opt_weight_lbs, req_str, req_bool
from routes.common import list_endpoint, require_record

bp = Blueprint("salvage", __name__)

PM = ["ProgramManager"]
CO = ["ComplianceOfficer"]
BA = ["BillingAnalyst"]


@bp.route("/streetlights/salvage-batches", methods=["POST"])
@locked
def create_salvage_batch():
    caller = get_caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    batch_label = req_str(body, "batch_label")
    require_roles(caller, PM)
    program = store.programs.get(program_id)
    if program is None:
        raise_error("ERR_PROGRAM_NOT_FOUND", f"program not found: {program_id}")
    require_active(program)
    for b in store.salvage_batches.values():
        if b["program_id"] == program_id and b["batch_label"] == batch_label:
            raise_error("ERR_INVALID_REQUEST", "batch_label must be unique within the program")
    rec = new_record("salvage_batches", {
        "program_id": program_id,
        "batch_label": batch_label,
        "contaminated_flag": None,
        "settlement_value_cents": None,
        "manifest_code": None,
        "status": "ACCUMULATING",
    })
    return success_object(ser_batch(rec), status=201)


@bp.route("/streetlights/salvage-batches", methods=["GET"])
@locked
def list_salvage_batches():
    return list_endpoint("salvage_batches", ser_batch, ["program_id", "status"])


@bp.route("/streetlights/salvage-batches/<bid>", methods=["GET"])
@locked
def get_salvage_batch(bid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    return success_object(ser_batch(rec))


@bp.route("/streetlights/salvage-batches/<bid>/items", methods=["POST"])
@locked
def add_salvage_item(bid):
    caller = get_caller()
    body = get_body()
    salvage_item_id = req_str(body, "salvage_item_id")
    weight = opt_weight_lbs(body, "weight_lbs")
    mercury = opt_bool(body, "mercury_flag", default=None)
    require_roles(caller, PM)
    batch = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    item = store.salvage_items.get(salvage_item_id)
    if item is None:
        raise_error("ERR_SALVAGE_ITEM_NOT_FOUND", f"salvage item not found: {salvage_item_id}")
    require_active(store.programs.get(batch["program_id"]))
    if batch["status"] != "ACCUMULATING":
        raise_error("ERR_BATCH_NOT_ACCUMULATING", "items may be added only while ACCUMULATING")
    if item["batch_id"] is not None:
        raise_error("ERR_SALVAGE_ITEM_ALREADY_BATCHED", "item is not in the unbatched pool")
    item["batch_id"] = batch["id"]
    if weight is not None:
        item["weight_lbs"] = float(weight)
    if mercury is not None:
        item["mercury_flag"] = mercury
    touch(item)
    return success_object(ser_salvage_item(item))


@bp.route("/streetlights/salvage-items", methods=["GET"])
@locked
def list_salvage_items():
    return list_endpoint("salvage_items", ser_salvage_item,
                         ["batch_id", "pole_id", "fixture_class"])


@bp.route("/streetlights/salvage-items/<iid>", methods=["GET"])
@locked
def get_salvage_item(iid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("salvage_items", iid, "ERR_SALVAGE_ITEM_NOT_FOUND")
    return success_object(ser_salvage_item(rec))


@bp.route("/streetlights/salvage-batches/<bid>/seal", methods=["POST"])
@locked
def seal_salvage_batch(bid):
    caller = get_caller()
    body = get_body()
    contaminated = req_bool(body, "contaminated_flag")
    require_roles(caller, CO)
    batch = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    require_active(store.programs.get(batch["program_id"]))
    if batch["status"] != "ACCUMULATING":
        raise_error("ERR_BATCH_NOT_ACCUMULATING", "seal requires an ACCUMULATING batch")
    if batch_item_count(batch) < 1:
        raise_error("ERR_EMPTY_BATCH", "batch must contain at least one item to seal")
    batch["contaminated_flag"] = contaminated
    batch["status"] = "SEALED"
    touch(batch)
    return success_object(ser_batch(batch))


@bp.route("/streetlights/salvage-batches/<bid>/manifest", methods=["POST"])
@locked
def manifest_salvage_batch(bid):
    caller = get_caller()
    require_roles(caller, CO)
    batch = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    require_active(store.programs.get(batch["program_id"]))
    if batch["status"] != "SEALED":
        raise_error("ERR_BATCH_NOT_SEALED", "manifest requires a SEALED batch")
    items = [i for i in store.salvage_items.values() if i["batch_id"] == batch["id"]]
    if any(not i["weight_lbs"] or i["weight_lbs"] <= 0 for i in items):
        raise_error("ERR_UNWEIGHED_ITEMS", "every item must have weight_lbs > 0 to manifest")
    batch["manifest_code"] = "MF-" + batch["batch_label"]
    batch["settlement_value_cents"] = salvage_settlement_value(batch)
    batch["status"] = "MANIFESTED"
    touch(batch)
    return success_object(ser_batch(batch))


@bp.route("/streetlights/salvage-batches/<bid>/settle", methods=["POST"])
@locked
def settle_salvage_batch(bid):
    caller = get_caller()
    require_roles(caller, BA)
    batch = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    program = store.programs.get(batch["program_id"])
    require_active(program)
    if batch["status"] != "MANIFESTED":
        raise_error("ERR_BATCH_NOT_MANIFESTED", "settle requires a MANIFESTED batch")
    post_budget(program, batch["settlement_value_cents"])
    bump_program(program)
    batch["status"] = "SETTLED"
    touch(batch)
    return success_object(ser_batch(batch))


@bp.route("/streetlights/salvage-batches/<bid>/reject", methods=["POST"])
@locked
def reject_salvage_batch(bid):
    caller = get_caller()
    require_roles(caller, CO)
    batch = require_record("salvage_batches", bid, "ERR_BATCH_NOT_FOUND")
    require_active(store.programs.get(batch["program_id"]))
    if batch["status"] not in ("SEALED", "MANIFESTED"):
        raise_error("ERR_BATCH_NOT_REJECTABLE", "reject requires a SEALED or MANIFESTED batch")
    for item in store.salvage_items.values():
        if item["batch_id"] == batch["id"]:
            item["batch_id"] = None
            touch(item)
    batch["settlement_value_cents"] = None
    batch["status"] = "REJECTED"
    touch(batch)
    return success_object(ser_batch(batch))
