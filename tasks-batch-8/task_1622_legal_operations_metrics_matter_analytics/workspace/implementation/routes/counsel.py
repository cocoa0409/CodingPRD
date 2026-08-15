from flask import Blueprint, request

from db import store, new_entity
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response
from serializers import counsel_view
from services.aggregates import counsel_utilization
from validation import Payload, require_exists, list_page

bp = Blueprint("counsel", __name__, url_prefix="/legal-ops/in-house-counsel")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


@bp.post("")
@require_roles("LegalOpsManager")
def create_counsel(user_id, role):
    p = Payload()
    full_name = p.req_str("full_name")
    email = p.req_str("email")
    capacity = p.req_int("annual_capacity_hours")
    cost = p.req_int("loaded_hourly_cost_cents")
    if email is not None:
        for c in store.counsel.values():
            if c["email"] == email:
                raise ApiError(ERR_DUPLICATE, 409, "Counsel email already exists")
    p.finish()
    if capacity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "annual_capacity_hours must be > 0")
    if cost < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "loaded_hourly_cost_cents must be >= 0")
    c = new_entity({
        "full_name": full_name,
        "email": email,
        "annual_capacity_hours": capacity,
        "loaded_hourly_cost_cents": cost,
        "status": "ACTIVE",
    })
    store.counsel[c["id"]] = c
    return object_response(counsel_view(c), 201)


@bp.get("")
@require_roles(*ALL)
def list_counsel(user_id, role):
    items = list(store.counsel.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_page(items, counsel_view)


@bp.get("/<cid>")
@require_roles(*ALL)
def get_counsel(user_id, role, cid):
    return object_response(counsel_view(require_exists(store.counsel, cid, "counsel")))


@bp.get("/<cid>/utilization")
@require_roles(*ALL)
def get_utilization(user_id, role, cid):
    c = require_exists(store.counsel, cid, "counsel")
    return object_response(counsel_utilization(c))
