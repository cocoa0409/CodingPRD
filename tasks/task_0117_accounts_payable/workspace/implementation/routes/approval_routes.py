"""ApprovalRoute endpoint (PRD §3.1).

Lightweight record: id + created_at only (no updated_at/version).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import auth_required
from response import ok_object
from routes._helpers import get_body, require_fields, serialize, is_int
from services.common import new_lightweight_fields

bp = Blueprint("approval_routes", __name__)


@bp.post("/ap/approval-routes")
def create_approval_route():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["min_amount_cents", "max_amount_cents", "required_levels"])

    min_amount = body["min_amount_cents"]
    if not is_int(min_amount) or min_amount < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "min_amount_cents must be an integer >= 0")

    max_amount = body["max_amount_cents"]
    if not is_int(max_amount):
        raise APIError(ERR_INVALID_REQUEST, 400, "max_amount_cents must be an integer")
    if max_amount <= min_amount:
        raise APIError(ERR_INVALID_REQUEST, 400, "max_amount_cents must be greater than min_amount_cents")

    required_levels = body["required_levels"]
    if not is_int(required_levels) or required_levels < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "required_levels must be an integer >= 1")

    route = {
        **new_lightweight_fields(),
        "min_amount_cents": min_amount,
        "max_amount_cents": max_amount,
        "required_levels": required_levels,
    }
    db.approval_routes[route["id"]] = route
    return ok_object(serialize(route), http_status=201)
