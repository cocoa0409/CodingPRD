"""Picker endpoints (PRD §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_PICKER_NOT_FOUND, ERR_STORE_NOT_FOUND
from middleware import get_user_context, require_role
import validate as V
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("pickers", __name__)


@bp.route("/v1/pickers", methods=["POST"])
def create_picker():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    body = V.get_body()
    store_id = V.require_str(body, "store_id")
    full_name = V.require_str(body, "full_name")
    cooldown = V.opt_int(body, "window_cooldown_minutes", 15, minimum=0)  # default 15
    with db.lock:
        if store_id not in db.stores:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        picker = {
            "store_id": store_id,
            "full_name": full_name,
            "window_cooldown_minutes": cooldown,
            "status": "AVAILABLE",  # PRD §3.1: begins AVAILABLE
        }
        db.stamp_create(picker)
        db.pickers[picker["id"]] = picker
        return object_response(public(picker), 201)


@bp.route("/v1/pickers", methods=["GET"])
def list_pickers():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Picker"})  # PRD §4
    limit, offset = get_pagination()
    store_id = request.args.get("store_id")
    with db.lock:
        records = list(db.pickers.values())
        if store_id is not None:
            records = [p for p in records if p["store_id"] == store_id]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/pickers/<picker_id>", methods=["GET"])
def get_picker(picker_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Picker"})  # PRD §4
    with db.lock:
        picker = db.pickers.get(picker_id)
        if picker is None:
            err(ERR_PICKER_NOT_FOUND, "Picker not found")
        return object_response(public(picker))
