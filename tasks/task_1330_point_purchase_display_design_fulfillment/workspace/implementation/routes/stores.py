"""Store endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, paginate, sort_by_created, serialize,
)

bp = Blueprint("stores", __name__)

GET_STORE_ROLES = ("PlatformAdmin", "ProgramManager", "WarehouseOperator", "LogisticsCoordinator", "FieldServiceManager")


@bp.route("/pop/stores", methods=["POST"])
@require_roles("ProgramManager")
def create_store():
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    store_number = require_string(body, "store_number")
    address = require_string(body, "address")

    if not db.programs.get(program_id):
        raise errors.err_not_found("Program not found")

    for s in db.stores.values():
        if s["program_id"] == program_id and s["store_number"] == store_number:
            raise errors.err_duplicate("store_number already exists in this program")

    store = new_common_fields()
    store.update({
        "program_id": program_id,
        "store_number": store_number,
        "address": address,
    })
    db.stores[store["id"]] = store
    return response.success_object(serialize(store), 201)


@bp.route("/pop/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    _, role = get_auth()
    if role not in GET_STORE_ROLES:
        raise errors.err_unauthorized()
    store = db.stores.get(store_id)
    if not store:
        raise errors.err_not_found("Store not found")
    return response.success_object(serialize(store), 200)


@bp.route("/pop/programs/<program_id>/stores", methods=["GET"])
def list_program_stores(program_id):
    _, role = get_auth()
    if role not in GET_STORE_ROLES:
        raise errors.err_unauthorized()
    if not db.programs.get(program_id):
        raise errors.err_not_found("Program not found")
    items = sort_by_created([s for s in db.stores.values() if s["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(s) for s in page], limit, offset, total)
