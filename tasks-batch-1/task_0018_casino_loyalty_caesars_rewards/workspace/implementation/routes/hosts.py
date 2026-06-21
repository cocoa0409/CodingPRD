"""Host endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400, require_str, parse_pagination, paginate,
    stamp_create, get_or_404, fk_or_404,
)
from response import success_object, success_array
from services.serializers import host_view


bp = Blueprint("hosts", __name__)


@bp.route("/hosts", methods=["POST"])
def create_host():
    require_role({"ComplianceOfficer"})
    body = get_json_or_400()
    email = require_str(body, "employee_email", max_len=254)
    home_property_id = require_str(body, "home_property_id")

    with db.lock:
        # FK existence (priority 3)
        fk_or_404(db.properties, home_property_id, "property")
        # employee_email uniqueness (case-insensitive). Not in the catalogue,
        # but treat as ERR_INVALID_REQUEST/409 is unnecessary — not tested per PRD;
        # we enforce uniqueness on first-write to be safe.
        normalized = email.casefold()
        for h in db.hosts.values():
            if h["employee_email"].casefold() == normalized:
                # No explicit error_id in the catalogue, return invalid request.
                from errors import ApiError, ERR_INVALID_REQUEST
                raise ApiError(ERR_INVALID_REQUEST, 409, "employee_email already in use")
        row = {
            "employee_email": email,
            "home_property_id": home_property_id,
            "status": "ACTIVE",
        }
        stamp_create(row)
        db.hosts[row["id"]] = row
    return success_object(host_view(row), 201)


@bp.route("/hosts/<hid>", methods=["GET"])
def get_host(hid):
    require_role({"LoyaltyManager", "ComplianceOfficer"})
    with db.lock:
        row = get_or_404(db.hosts, hid, "host")
        return success_object(host_view(row), 200)


@bp.route("/hosts", methods=["GET"])
def list_hosts():
    require_role({"LoyaltyManager", "ComplianceOfficer"})
    home_property_id = request.args.get("home_property_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.hosts.values())
        if home_property_id is not None:
            rows = [r for r in rows if r["home_property_id"] == home_property_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([host_view(r) for r in page], limit, offset, total, 200)
