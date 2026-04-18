from flask import Blueprint, request

from errors import raise_error
from response import success
from middleware import require_roles
from util import add_common_fields
from util_pagination import parse_pagination, paginate
from db import db

bp = Blueprint("resources", __name__)


VALID_KINDS = {"WORKSTATION", "MEETING_ROOM", "EVENT_AREA"}


def resource_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "kind": r["kind"],
        "code": r["code"],
        "capacity": r["capacity"],
        "hourly_rate_cents": r["hourly_rate_cents"],
        "daily_rate_cents": r["daily_rate_cents"],
        "block_rate_cents": r["block_rate_cents"],
        "status": r["status"],
    }


@bp.route("/resources", methods=["POST"])
def create_resource():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    code = body.get("code")
    capacity = body.get("capacity")
    hourly = body.get("hourly_rate_cents", 0)
    daily = body.get("daily_rate_cents", 0)
    block = body.get("block_rate_cents", 0)

    if kind not in VALID_KINDS:
        raise_error(("ERR_INVALID_INPUT", 422), f"kind must be one of {VALID_KINDS}")
    if not isinstance(code, str) or not code:
        raise_error(("ERR_INVALID_INPUT", 422), "code is required")
    if not isinstance(capacity, int) or capacity < 1:
        raise_error(("ERR_INVALID_INPUT", 422), "capacity must be >= 1")
    for name, val in (("hourly_rate_cents", hourly), ("daily_rate_cents", daily), ("block_rate_cents", block)):
        if not isinstance(val, int) or val < 0:
            raise_error(("ERR_INVALID_INPUT", 422), f"{name} must be >= 0")

    if db.resource_by_code(code):
        raise_error(("ERR_INVALID_INPUT", 422), "Resource code already exists")

    resource = {
        "kind": kind,
        "code": code,
        "capacity": capacity,
        "hourly_rate_cents": hourly,
        "daily_rate_cents": daily,
        "block_rate_cents": block,
        "status": "AVAILABLE",
    }
    add_common_fields(resource, db.now(), db.new_id())
    db.resources[resource["id"]] = resource
    return success(resource_view(resource), 201)


@bp.route("/resources", methods=["GET"])
def list_resources():
    require_roles("PlatformAdmin", "TenantAdmin", "TenantMember")
    kind = request.args.get("kind")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(db.resources.values())
    if kind:
        items = [r for r in items if r["kind"] == kind]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([resource_view(r) for r in page], pagination=meta)
