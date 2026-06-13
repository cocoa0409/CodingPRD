"""PrepBatch endpoints (PRD §3.5)."""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from clock import now_iso
from errors import err
from helpers import get_body, require_str, require_fk, require_int, get_pagination, paginate
from lookups import get_prep_batch, get_truck, get_menu_item
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("prep_batches", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/prep-batches")
def create_prep_batch():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    menu_item_id = require_fk(body, "menu_item_id")
    get_truck(truck_id)
    get_menu_item(menu_item_id)
    require_truck_ownership(user_id, role, truck_id)
    units_made = require_int(body, "units_made", minimum=1)
    rec = db.new_record({
        "truck_id": truck_id,
        "menu_item_id": menu_item_id,
        "units_made": units_made,
        "prepped_at": now_iso(),
        "status": "OPEN",
    })
    db.prep_batches[rec["id"]] = rec
    return ok_object(serializers.prep_batch(rec), 201)


@bp.get("/prep-batches")
def list_prep_batches():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.prep_batches.values())
    for field in ("truck_id", "menu_item_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.prep_batch(r) for r in window], limit, offset, total)


@bp.get("/prep-batches/<batch_id>")
def get_prep_batch_route(batch_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_prep_batch(batch_id)
    return ok_object(serializers.prep_batch(rec))


@bp.post("/prep-batches/<batch_id>/discard")
def discard_prep_batch(batch_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_prep_batch(batch_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    if rec["status"] != "OPEN":
        raise err(errors.ERR_BATCH_NOT_OPEN, "Prep batch is not OPEN")
    # Removing this batch must not drive prepared_units below 0 (§3.5).
    if services.prepared_units(rec["menu_item_id"]) - rec["units_made"] < 0:
        raise err(errors.ERR_PREPARED_UNITS_NEGATIVE,
                  "Discard would drive prepared_units below 0")
    rec["status"] = "DISCARDED"
    db.touch(rec)
    return ok_object(serializers.prep_batch(rec))
