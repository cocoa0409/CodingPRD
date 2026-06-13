"""Allocation endpoints (PRD §3.8) — reserve / release with OCC + fill check."""
from flask import Blueprint, request

from db import db
from common import (new_record, touch, serialize, get_body, require_str,
                    require_field, must_exist, paginate)
from middleware import authenticate, require_roles
from response import success, list_success
from errors import (err, ERR_INVALID_STATE, ERR_STALE_WAVE_VERSION,
                    ERR_BOX_ALREADY_FINALIZED, ERR_CUTOFF_PASSED)
from services.inventory import reserve, release_allocation

bp = Blueprint("allocations", __name__)


@bp.post("/allocations")
def create_allocation():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    subscription_id = require_str(body, "subscription_id")
    wave_id = require_str(body, "wave_id")
    box_selection_id = require_str(body, "box_selection_id")
    expected_wave_version = require_field(body, "expected_wave_version")

    # existence (priority 3): body FKs left-to-right
    must_exist(db.subscriptions, subscription_id, "Subscription")
    wave = must_exist(db.shipping_waves, wave_id, "ShippingWave")
    box = must_exist(db.box_selections, box_selection_id, "BoxSelection")

    # state (priority 5): referenced wave must be OPEN
    if wave["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Reservation requires an OPEN wave.")

    # OCC (priority 6): expected_wave_version == live wave.version
    if expected_wave_version != wave["version"]:
        raise err(ERR_STALE_WAVE_VERSION, "Wave version is stale.")

    # business (priority 8): box already finalized into a non-released allocation
    if box["decision"] == "FINALIZED" and box.get("allocation_id"):
        existing = db.allocations.get(box["allocation_id"])
        if existing and existing["status"] != "RELEASED":
            raise err(ERR_BOX_ALREADY_FINALIZED,
                      "Box period already holds a non-released allocation.")

    # temporal (priority 9): clock must be strictly before cutoff_at
    if db.now() >= wave["cutoff_at"]:
        raise err(ERR_CUTOFF_PASSED, "Cutoff has passed for this wave.")

    # safety (10) + capacity (11): all-or-nothing fill check; mutates products + wave
    line_items = reserve(box, wave)

    alloc = new_record({
        "subscription_id": subscription_id,
        "wave_id": wave_id,
        "box_selection_id": box_selection_id,
        "line_items": line_items,
        "status": "RESERVED",
    })
    db.allocations[alloc["id"]] = alloc

    box["decision"] = "FINALIZED"
    box["allocation_id"] = alloc["id"]
    touch(box)
    return success(serialize(alloc), status=201)


@bp.get("/allocations/<aid>")
def get_allocation(aid):
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    alloc = must_exist(db.allocations, aid, "Allocation")
    return success(serialize(alloc))


@bp.get("/allocations")
def list_allocations():
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    records = list(db.allocations.values())
    wave_filter = request.args.get("wave_id")
    if wave_filter is not None:
        records = [r for r in records if r["wave_id"] == wave_filter]
    sub_filter = request.args.get("subscription_id")
    if sub_filter is not None:
        records = [r for r in records if r["subscription_id"] == sub_filter]
    box_filter = request.args.get("box_selection_id")
    if box_filter is not None:
        records = [r for r in records if r["box_selection_id"] == box_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/allocations/<aid>/release")
def release_allocation_route(aid):
    authenticate()
    require_roles("CurationAdmin")
    alloc = must_exist(db.allocations, aid, "Allocation")
    if alloc["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Release requires a RESERVED allocation.")
    release_allocation(alloc, revert_decision="CURATED")
    return success(serialize(alloc))
