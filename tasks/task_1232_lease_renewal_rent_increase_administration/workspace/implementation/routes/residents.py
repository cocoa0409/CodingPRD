from flask import Blueprint, request

from db import store
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESIDENT_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from services.common import new_entity

bp = Blueprint("residents", __name__)


def _serialize(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "full_name": r["full_name"],
        "email": r["email"],
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@bp.route("/residents", methods=["POST"])
def create_resident():
    require_roles("PlatformAdmin", "PropertyManager", "LeasingAgent")
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    email = body.get("email")
    if not full_name or not isinstance(full_name, str):
        raise_err(ERR_INVALID_REQUEST, "full_name required")
    if not email or not isinstance(email, str):
        raise_err(ERR_INVALID_REQUEST, "email required")
    rec = new_entity()
    rec.update({"full_name": full_name, "email": email})
    store.residents[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/residents", methods=["GET"])
def list_residents():
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    limit, offset = _get_pagination()
    items = list(store.residents.values())
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(r) for r in page], limit, offset, total)


@bp.route("/residents/<rid>", methods=["GET"])
def get_resident(rid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    r = store.residents.get(rid)
    if r is None:
        raise_err(ERR_RESIDENT_NOT_FOUND, "resident not found")
    return success_object(_serialize(r))
