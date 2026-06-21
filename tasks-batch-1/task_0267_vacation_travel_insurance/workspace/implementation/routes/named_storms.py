"""Named storm endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize
from services.store_helpers import make_record, touch, get_named_storm

bp = Blueprint("named_storms", __name__)

BASINS = {"ATLANTIC", "EAST_PACIFIC", "WEST_PACIFIC", "INDIAN"}


@bp.route("/named-storms", methods=["POST"])
@require_roles("CarrierAdmin")
def create_storm():
    body = common.get_json_body()
    name = common.require_str(body, "name")
    basin = common.require_enum(body, "basin", BASINS)
    named_at = common.require_datetime(body, "named_at")

    for s in db.named_storms.values():
        if s["name"] == name:
            raise errors.conflict(errors.ERR_DUPLICATE_NAME, "Named storm name already in use.")

    rec = make_record()
    rec.update({
        "name": name,
        "basin": basin,
        "named_at": body["named_at"],
        "_named_at_dt": named_at,
        "status": "ACTIVE",
    })
    db.named_storms[rec["id"]] = rec
    return response.success_object(serialize.named_storm_out(rec), status=201)


@bp.route("/named-storms/<storm_id>", methods=["GET"])
@require_roles("Any")
def get_storm_route(storm_id):
    rec = get_named_storm(storm_id)
    return response.success_object(serialize.named_storm_out(rec), status=200)


@bp.route("/named-storms", methods=["GET"])
@require_roles("Any")
def list_storms():
    basin = request.args.get("basin")
    status = request.args.get("status")
    items = list(db.named_storms.values())
    if basin is not None:
        items = [s for s in items if s["basin"] == basin]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.named_storm_out(s) for s in page], limit, offset, total)


@bp.route("/named-storms/<storm_id>/dissipate", methods=["POST"])
@require_roles("CarrierAdmin")
def dissipate_storm(storm_id):
    rec = get_named_storm(storm_id)
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Named storm is not ACTIVE.")
    rec["status"] = "DISSIPATED"
    touch(rec)
    return response.success_object(serialize.named_storm_out(rec), status=200)
