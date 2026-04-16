"""Shelter routes."""

from flask import Blueprint, request

from db import store, new_id, now_dt, lock
from middleware import auth_required
from response import success_object, success_array
from errors import raise_err, ERR_INVALID_REQUEST
from services.validation import (
    get_json_body, require_field, pagination, get_shelter_or_404,
)
from services.serializers import serialize_shelter

bp = Blueprint("shelters", __name__)


@bp.route("/shelters", methods=["POST"])
@auth_required(allowed_roles={"ShelterAdmin"})
def create_shelter():
    body = get_json_body(required=True)
    name = require_field(body, "name", types=str)
    cap = require_field(body, "boarding_capacity", types=int)
    fee_base = require_field(body, "adoption_fee_base", types=int)
    rate = require_field(body, "boarding_rate_per_night", types=int)
    if isinstance(cap, bool) or isinstance(fee_base, bool) or isinstance(rate, bool):
        raise_err(ERR_INVALID_REQUEST, "Numeric fields must be integers")
    if cap < 0 or fee_base < 0 or rate < 0:
        raise_err(ERR_INVALID_REQUEST, "Numeric fields must be non-negative")
    with lock:
        sid = new_id()
        now = now_dt()
        rec = {
            "id": sid,
            "name": name,
            "boarding_capacity": cap,
            "adoption_fee_base": fee_base,
            "boarding_rate_per_night": rate,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.shelters[sid] = rec
    return success_object(serialize_shelter(rec), status_code=201)


@bp.route("/shelters", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def list_shelters():
    limit, offset = pagination()
    status_filter = request.args.get("status")
    all_shelters = list(store.shelters.values())
    if status_filter:
        all_shelters = [s for s in all_shelters if s["status"] == status_filter]
    all_shelters.sort(key=lambda r: r["created_at"])
    total = len(all_shelters)
    page = all_shelters[offset: offset + limit]
    return success_array([serialize_shelter(r) for r in page], limit, offset, total)


@bp.route("/shelters/<sid>", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def get_shelter(sid):
    rec = get_shelter_or_404(sid)
    return success_object(serialize_shelter(rec))
