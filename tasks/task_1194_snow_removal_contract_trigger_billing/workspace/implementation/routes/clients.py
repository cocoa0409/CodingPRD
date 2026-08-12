"""Client endpoints."""
from flask import Blueprint
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNERSHIP

bp = Blueprint("clients", __name__)

ALLOWED_CREATE_FIELDS = {"name", "credit_limit_cents"}


@bp.route("/clients", methods=["POST"])
def create_client():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)
    name = body.get("name")
    credit_limit = body.get("credit_limit_cents")
    if not name:
        raise ApiError(ERR_INVALID_REQUEST, "name is required", 400)
    if credit_limit is None:
        raise ApiError(ERR_INVALID_REQUEST, "credit_limit_cents is required", 400)

    client = {
        "id": db._new_id(),
        "name": name,
        "credit_limit_cents": credit_limit,
        "credit_exposure_cents": 0,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.clients.create(client)
    return success_created(client)


@bp.route("/clients/<id>", methods=["GET"])
def get_client(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    client = db.clients.get(id)
    if not client:
        raise ApiError(ERR_NOT_FOUND, f"Client {id} not found", 404)
    # ClientContact ownership check
    if role == "ClientContact" and client["id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your client", 403)
    return success_object(client)


@bp.route("/clients", methods=["GET"])
def list_clients():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher")
    limit, offset = get_pagination()
    all_clients = sorted(db.clients.list_all(), key=lambda c: c.get("created_at", ""))
    total = len(all_clients)
    page = all_clients[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/clients/<id>/sites", methods=["GET"])
def list_client_sites(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    client = db.clients.get(id)
    if not client:
        raise ApiError(ERR_NOT_FOUND, f"Client {id} not found", 404)
    if role == "ClientContact" and client["id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your client", 403)
    limit, offset = get_pagination()
    all_sites = sorted(
        [s for s in db.sites.list_all() if s.get("client_id") == id],
        key=lambda s: s.get("created_at", ""),
    )
    total = len(all_sites)
    page = all_sites[offset:offset + limit]
    return success_list(page, total, limit, offset)
