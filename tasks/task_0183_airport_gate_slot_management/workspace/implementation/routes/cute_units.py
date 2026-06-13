"""CuteUnit registry routes + reverse-FK allocation listing."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("cute_units", __name__)


@bp.route("/cute-units", methods=["POST"])
def create_cute_unit():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["label", "terminal"])
    label = body["label"]
    terminal = body["terminal"]
    if not isinstance(label, str) or not isinstance(terminal, str):
        raise errors.invalid_request("label and terminal must be strings.")
    rec = {
        "id": db.new_id(),
        "label": label,
        "terminal": terminal,
        "status": "AVAILABLE",
    }
    db.stamp_create(rec)
    db.cute_units[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/cute-units/<cid>", methods=["GET"])
def get_cute_unit(cid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "RampAgent", "GateController"})
    rec = db.cute_units.get(cid)
    if rec is None:
        raise errors.not_found("CUTE unit not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/cute-units/<cid>/cute-allocations", methods=["GET"])
def allocations_for_cute_unit(cid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "RampAgent"})
    if cid not in db.cute_units:
        raise errors.not_found("CUTE unit not found.")
    status = request.args.get("status")
    recs = [a for a in db.cute_allocations.values() if a.get("cute_unit_id") == cid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)
