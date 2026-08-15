"""Location endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_LOCATION_NOT_FOUND,
    ERR_LOCATION_MATERIALITY_TOO_HIGH,
)
from services.core import stamp_new, get_engagement_or_404

bp = Blueprint("locations", __name__)


@bp.route("/api/locations", methods=["POST"])
def create_location():
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    location_code = body.get("location_code")
    name = body.get("name")
    materiality_cents = body.get("materiality_cents")

    if not isinstance(engagement_id, str) or not engagement_id.strip():
        raise ApiError("ERR_VALIDATION", "engagement_id is required", 400)
    eng = get_engagement_or_404(engagement_id)
    if not isinstance(location_code, str) or not location_code.strip():
        raise ApiError("ERR_VALIDATION", "location_code is required", 400)
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_VALIDATION", "name is required", 400)
    if (
        not isinstance(materiality_cents, int)
        or isinstance(materiality_cents, bool)
        or materiality_cents <= 0
    ):
        raise ApiError("ERR_VALIDATION", "materiality_cents must be > 0", 400)
    if materiality_cents > eng["materiality_cents"]:
        raise ApiError(
            ERR_LOCATION_MATERIALITY_TOO_HIGH,
            "Location.materiality_cents must be <= engagement.materiality_cents",
            422,
        )

    loc = stamp_new(
        {
            "engagement_id": engagement_id,
            "location_code": location_code,
            "name": name,
            "materiality_cents": materiality_cents,
        }
    )
    db.locations[loc["id"]] = loc
    return success_object(dict(loc), 201)


@bp.route("/api/locations", methods=["GET"])
def list_locations():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    items = list(db.locations.values())
    if engagement_id:
        items = [l for l in items if l["engagement_id"] == engagement_id]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(l) for l in page], limit, offset, total)


@bp.route("/api/locations/<location_id>", methods=["GET"])
def get_location(location_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    loc = db.locations.get(location_id)
    if loc is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, "Location id not found", 404)
    return success_object(dict(loc))
