"""Client endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import new_common_fields, require_string, paginate, sort_by_created, serialize

bp = Blueprint("clients", __name__)

ALL_ROLES = (
    "PlatformAdmin", "ProgramManager", "Designer", "ComplianceOfficer",
    "ProductionPlanner", "WarehouseOperator", "LogisticsCoordinator",
    "ClaimsAdjuster", "FieldServiceManager",
)


@bp.route("/pop/clients", methods=["POST"])
@require_roles("PlatformAdmin")
def create_client():
    body = request.get_json(silent=True) or {}
    name = require_string(body, "name")
    contact_email = require_string(body, "contact_email")
    client = new_common_fields()
    client.update({
        "name": name,
        "contact_email": contact_email,
        "status": "ACTIVE",
    })
    db.clients[client["id"]] = client
    return response.success_object(serialize(client), 201)


@bp.route("/pop/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    _, role = get_auth()
    if role not in ALL_ROLES:
        raise errors.err_unauthorized()
    client = db.clients.get(client_id)
    if not client:
        raise errors.err_not_found("Client not found")
    return response.success_object(serialize(client), 200)


@bp.route("/pop/clients/<client_id>/programs", methods=["GET"])
def list_client_programs(client_id):
    _, role = get_auth()
    if role not in ("PlatformAdmin", "ProgramManager"):
        raise errors.err_unauthorized()
    client = db.clients.get(client_id)
    if not client:
        raise errors.err_not_found("Client not found")
    items = sort_by_created([p for p in db.programs.values() if p["client_id"] == client_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(p) for p in page], limit, offset, total)
