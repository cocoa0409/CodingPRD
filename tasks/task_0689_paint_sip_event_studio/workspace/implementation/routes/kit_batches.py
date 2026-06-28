"""CanvasKitBatch endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response

bp = Blueprint("kit_batches", __name__)


@bp.post("/studio-ops/kit-batches")
def create_kit_batch():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    event_id = helpers.as_str(body, "event_id")
    sku = helpers.as_str(body, "sku")
    prepared = helpers.as_int(body, "prepared_count", min_value=0)
    if not db.events.get(event_id):
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "event_id does not exist")
    rec = models.make_kit_batch(event_id, sku, prepared)
    db.kit_batches[rec["id"]] = rec
    return object_response(models.serialize_kit_batch(rec), 201)


@bp.get("/studio-ops/kit-batches/<kid>")
def get_kit_batch(kid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "PlatformAdmin")
    rec = db.kit_batches.get(kid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Kit batch not found")
    return object_response(models.serialize_kit_batch(rec), 200)


@bp.get("/studio-ops/kit-batches")
def list_kit_batches():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    event_id = request.args.get("event_id")
    rows = list(db.kit_batches.values())
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_kit_batch(r) for r in page],
                          limit, offset, total, 200)
