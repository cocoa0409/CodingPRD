"""Site endpoints."""
from flask import Blueprint
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNERSHIP

bp = Blueprint("sites", __name__)

ALLOWED_CREATE_FIELDS = {"client_id", "name", "address", "region_code", "pavement_area_sqft", "requires_loader"}


@bp.route("/sites", methods=["POST"])
def create_site():
    user_id, role = require_roles("OpsDispatcher", "ClientContact")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)
    client_id = body.get("client_id")
    if not client_id:
        raise ApiError(ERR_INVALID_REQUEST, "client_id is required", 400)
    client = db.clients.get(client_id)
    if not client:
        raise ApiError(ERR_NOT_FOUND, f"Client {client_id} not found", 404)
    if role == "ClientContact" and client_id != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Cannot create site for another client", 403)

    name = body.get("name")
    address = body.get("address")
    region_code = body.get("region_code")
    pavement_area = body.get("pavement_area_sqft")
    if not name:
        raise ApiError(ERR_INVALID_REQUEST, "name is required", 400)
    if not address:
        raise ApiError(ERR_INVALID_REQUEST, "address is required", 400)
    if not region_code:
        raise ApiError(ERR_INVALID_REQUEST, "region_code is required", 400)
    if pavement_area is None:
        raise ApiError(ERR_INVALID_REQUEST, "pavement_area_sqft is required", 400)

    site = {
        "id": db._new_id(),
        "client_id": client_id,
        "name": name,
        "address": address,
        "region_code": region_code,
        "pavement_area_sqft": pavement_area,
        "requires_loader": body.get("requires_loader", False),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.sites.create(site)
    return success_created(site)


@bp.route("/sites/<id>", methods=["GET"])
def get_site(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "Subcontractor")
    site = db.sites.get(id)
    if not site:
        raise ApiError(ERR_NOT_FOUND, f"Site {id} not found", 404)
    if role == "ClientContact" and site.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your site", 403)
    return success_object(site)


@bp.route("/sites/<id>/contract-sites", methods=["GET"])
def list_site_contract_sites(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    site = db.sites.get(id)
    if not site:
        raise ApiError(ERR_NOT_FOUND, f"Site {id} not found", 404)
    if role == "ClientContact" and site.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your site", 403)
    limit, offset = get_pagination()
    all_cs = sorted(
        [cs for cs in db.contract_sites.list_all() if cs.get("site_id") == id],
        key=lambda c: c.get("created_at", ""),
    )
    total = len(all_cs)
    page = all_cs[offset:offset + limit]
    return success_list(page, total, limit, offset)
