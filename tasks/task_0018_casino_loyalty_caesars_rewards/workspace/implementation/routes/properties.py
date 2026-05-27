"""Property endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_int, require_enum,
    parse_pagination, paginate, stamp_create, get_or_404,
)
from response import success_object, success_array
from services.serializers import property_view, member_view


bp = Blueprint("properties", __name__)

MARKET_SEGMENTS = {"VEGAS_STRIP", "REGIONAL", "INTERNATIONAL"}
PROPERTY_STATUSES = {"OPEN", "CLOSED"}


@bp.route("/properties", methods=["POST"])
def create_property():
    require_role({"ComplianceOfficer"})
    body = get_json_or_400()
    name = require_str(body, "name")
    market_segment = require_enum(body, "market_segment", MARKET_SEGMENTS)
    base_rate = require_int(body, "base_room_rate_cents", minimum=0)

    with db.lock:
        row = {
            "name": name,
            "market_segment": market_segment,
            "base_room_rate_cents": base_rate,
            "status": "OPEN",
        }
        stamp_create(row)
        db.properties[row["id"]] = row
    return success_object(property_view(row), 201)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    with db.lock:
        row = get_or_404(db.properties, pid, "property")
        return success_object(property_view(row), 200)


@bp.route("/properties", methods=["GET"])
def list_properties():
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    market_segment = request.args.get("market_segment")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.properties.values())
        if market_segment is not None:
            rows = [r for r in rows if r["market_segment"] == market_segment]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([property_view(r) for r in page], limit, offset, total, 200)


@bp.route("/properties/<pid>/members", methods=["GET"])
def list_property_members(pid):
    require_role({"MemberServices", "LoyaltyManager", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    with db.lock:
        # path-segment id must resolve first
        get_or_404(db.properties, pid, "property")
        rows = [m for m in db.members.values() if m["home_property_id"] == pid]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([member_view(r) for r in page], limit, offset, total, 200)
