"""Mold/depositor shape inventory (PRD §3.3)."""
from flask import Blueprint, request

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import ALL_ROLES, auth, body, is_int, paginate, require_fields
from response import success_list, success_object
from serializers import mold_json

molds_bp = Blueprint("molds", __name__)


@molds_bp.route("/molds", methods=["POST"])
def create_mold():
    auth(("ProductionPlanner",))
    b = body()
    require_fields(b, ["shape_code", "cavity_count"])
    if not isinstance(b["shape_code"], str) or not b["shape_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "shape_code is required and must be a non-empty string.")
    if not is_int(b["cavity_count"]) or b["cavity_count"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "cavity_count must be an integer > 0.")
    m = {
        "id": new_id(),
        "shape_code": b["shape_code"],
        "cavity_count": b["cavity_count"],
        "status": "AVAILABLE",
    }
    stamp_new(m)
    store.molds[m["id"]] = m
    return success_object(mold_json(m), 201)


@molds_bp.route("/molds", methods=["GET"])
def list_molds():
    auth(ALL_ROLES)
    items = list(store.molds.values())
    f = request.args.get("shape_code")
    if f is not None:
        items = [m for m in items if m["shape_code"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [m for m in items if m["status"] == f]
    items.sort(key=lambda m: m["created_at"])
    page, meta = paginate(items)
    return success_list([mold_json(m) for m in page], meta)
