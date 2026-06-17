"""Container endpoints (PRD section 3.1, 3.7)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import get_container, get_container_type, paginate
from middleware import require_auth, require_role
from response import success
from serialize import container as ser
import validate

bp = Blueprint("containers", __name__)


@bp.post("/containers")
def create_container():
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    body = validate.get_json_body()
    validate.require_fields(body, ["container_type_id", "asset_tag", "yard_code"])
    container_type_id = validate.require_string(body, "container_type_id")
    asset_tag = validate.require_string(body, "asset_tag")
    yard_code = validate.require_string(body, "yard_code")

    # existence of FK (priority 3).
    get_container_type(container_type_id)

    # asset_tag unique across all containers (priority 15).
    for c in db.containers.values():
        if c["asset_tag"] == asset_tag:
            raise err("ERR_DUPLICATE_RESOURCE", "asset_tag already in use")

    rec = db.insert_with_common(db.containers, {
        "container_type_id": container_type_id,
        "asset_tag": asset_tag,
        "yard_code": yard_code,
        "status": "IN_YARD",
        "current_order_id": None,
    })
    return success(ser(rec), status=201)


@bp.get("/containers")
def list_containers():
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher"])
    limit, offset = validate.get_pagination()
    records = list(db.containers.values())
    ct = request.args.get("container_type_id")
    coid = request.args.get("current_order_id")
    status = request.args.get("status")
    yard = request.args.get("yard_code")
    if ct is not None:
        records = [r for r in records if r["container_type_id"] == ct]
    if coid is not None:
        records = [r for r in records if r["current_order_id"] == coid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if yard is not None:
        records = [r for r in records if r["yard_code"] == yard]
    return paginate(records, ser, limit, offset)


@bp.get("/containers/<container_id>")
def get_container_ep(container_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher"])
    rec = get_container(container_id)
    return success(ser(rec), status=200)


@bp.post("/containers/<container_id>/return-to-yard")
def return_to_yard(container_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    rec = get_container(container_id)
    if rec["status"] != "AWAITING_DUMP":
        raise err("ERR_CONTAINER_NOT_AWAITING_DUMP", "Container is not AWAITING_DUMP")
    rec["status"] = "IN_YARD"
    rec["current_order_id"] = None
    db.touch(rec)
    return success(ser(rec), status=200)


@bp.post("/containers/<container_id>/retire-asset")
def retire_asset(container_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    rec = get_container(container_id)
    if rec["status"] != "IN_YARD":
        raise err("ERR_CONTAINER_NOT_AVAILABLE", "Container is not IN_YARD")
    rec["status"] = "OUT_OF_SERVICE"
    db.touch(rec)
    return success(ser(rec), status=200)


@bp.post("/containers/<container_id>/restore-asset")
def restore_asset(container_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    rec = get_container(container_id)
    if rec["status"] != "OUT_OF_SERVICE":
        raise err("ERR_CONTAINER_NOT_OUT_OF_SERVICE", "Container is not OUT_OF_SERVICE")
    rec["status"] = "IN_YARD"
    db.touch(rec)
    return success(ser(rec), status=200)
