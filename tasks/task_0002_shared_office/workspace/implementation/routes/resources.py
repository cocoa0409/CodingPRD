"""Resource routes."""
from flask import Blueprint, request

from common import stamp_new, get_json_body, paginate
from db import db
from errors import api_error
from middleware import require_roles
from response import success

bp = Blueprint("resources", __name__)


@bp.route("/resources", methods=["POST"])
def create_resource():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    kind = body.get("kind")
    code = body.get("code")
    capacity = body.get("capacity")

    if kind not in ("WORKSTATION", "MEETING_ROOM", "EVENT_AREA"):
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid kind")
    if not code:
        raise api_error("ERR_INVALID_TIME_WINDOW", "code required")
    if not isinstance(capacity, int) or capacity < 1:
        raise api_error("ERR_INVALID_TIME_WINDOW", "capacity must be integer >= 1")

    # code unique
    for r in db.resources.values():
        if r["code"] == code:
            raise api_error("ERR_INVALID_TIME_WINDOW", "code already exists")

    resource = {
        "kind": kind,
        "code": code,
        "capacity": capacity,
        "hourly_rate_cents": body.get("hourly_rate_cents", 0),
        "daily_rate_cents": body.get("daily_rate_cents", 0),
        "block_rate_cents": body.get("block_rate_cents", 0),
        "status": "AVAILABLE",
    }
    stamp_new(resource)
    db.resources[resource["id"]] = resource
    return success(resource, status=201)


@bp.route("/resources", methods=["GET"])
def list_resources():
    require_roles(["PlatformAdmin", "TenantAdmin", "TenantMember"])
    items = list(db.resources.values())
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind:
        items = [r for r in items if r["kind"] == kind]
    if status:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
