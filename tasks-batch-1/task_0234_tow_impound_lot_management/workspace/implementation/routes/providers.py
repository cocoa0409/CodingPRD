"""TowProvider endpoints."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services import providers as provider_svc
from services.serialize import public
from validators import optional_int, require_int, require_str

bp = Blueprint("providers", __name__)


def get_provider_or_404(provider_id):
    p = db.tow_providers.get(provider_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Tow provider not found")
    return p


@bp.route("/tow-providers", methods=["POST"])
def create_provider():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    body = get_json_body()
    company_name = require_str(body, "company_name")
    license_number = require_str(body, "license_number")
    rotation_rank = require_int(body, "rotation_rank", minimum=1)
    trailing = optional_int(body, "trailing_window_size", default=10, minimum=1)

    provider = {
        "company_name": company_name,
        "license_number": license_number,
        "rotation_rank": rotation_rank,
        "offers_received_count": 0,
        "offers_accepted_count": 0,
        "trailing_window_size": trailing,
        "status": "ACTIVE",
        "raw_standing_pct": 100.0,
        "effective_standing_pct": 100.0,
    }
    db.stamp_create(provider)
    provider_svc.recompute_standing(provider)
    db.tow_providers[provider["id"]] = provider
    return object_response(public(provider), 201)


@bp.route("/tow-providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "TowProvider", "AuctionOfficial"})
    p = get_provider_or_404(provider_id)
    provider_svc.recompute_standing(p)
    return object_response(public(p), 200)


@bp.route("/tow-providers/<provider_id>/suspend", methods=["POST"])
def suspend_provider(provider_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    p = get_provider_or_404(provider_id)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Provider is not ACTIVE")
    p["status"] = "SUSPENDED"
    provider_svc.recompute_standing(p)
    db.touch(p)
    return object_response(public(p), 200)


@bp.route("/tow-providers/<provider_id>/reinstate", methods=["POST"])
def reinstate_provider(provider_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    p = get_provider_or_404(provider_id)
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Provider is not SUSPENDED")
    p["status"] = "ACTIVE"
    provider_svc.recompute_standing(p)
    db.touch(p)
    return object_response(public(p), 200)
