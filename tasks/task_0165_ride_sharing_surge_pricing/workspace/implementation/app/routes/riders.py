"""Rider endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import success_object
from ..errors import err_not_owner
from ..serializers import serialize_rider
from ..store import store
from ..util import new_uuid
from ._helpers import get_json, get_rider_or_404, require_string

bp = Blueprint("riders", __name__)


@bp.route("/riders", methods=["POST"])
@require_roles(["PlatformAdmin"])
def create_rider():
    body = get_json()
    name = require_string(body, "name")
    s = store()
    now = s.now()
    rid = new_uuid()
    rider = {
        "id": rid,
        "name": name,
        "wallet_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("riders", rider)
    return jsonify(success_object(serialize_rider(rider))), 201


@bp.route("/riders/<rider_id>", methods=["GET"])
@require_roles(["PlatformAdmin", "Rider"])
def get_rider(rider_id):
    r = get_rider_or_404(rider_id)
    user_id, role = current_user()
    if role == "Rider" and user_id != rider_id:
        raise err_not_owner()
    return jsonify(success_object(serialize_rider(r))), 200
