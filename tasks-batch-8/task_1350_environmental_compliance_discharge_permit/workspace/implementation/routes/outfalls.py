"""Outfall endpoints."""

import uuid
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PERMIT_NOT_FOUND,
    ERR_OUTFALL_NOT_FOUND,
    ERR_DUPLICATE_OUTFALL_NUMBER,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_OUTFALL_INACTIVE,
    ERR_OUTFALL_NOT_INACTIVE,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_outfall,
    paginate,
    cascade_outfall_deactivate,
)

bp = Blueprint("outfalls", __name__)


@bp.route("/npdes/outfalls", methods=["POST"])
def create_outfall():
    user_id, role = require_roles(["EnvironmentalManager"])
    body = get_body()
    require_fields(body, ["permit_id", "outfall_number"])
    permit = db.permits.get(body["permit_id"])
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    outfall_number = body["outfall_number"]
    if not isinstance(outfall_number, str) or not outfall_number:
        raise err(ERR_INVALID_REQUEST, 400, "outfall_number must be a non-empty string")
    if permit["status"] not in ("DRAFT", "ACTIVE"):
        raise err(ERR_PERMIT_NOT_ACTIVE, 409, "Outfalls may only be added while permit is DRAFT or ACTIVE")
    for o in db.outfalls.values():
        if o["permit_id"] == permit["id"] and o["outfall_number"] == outfall_number:
            raise err(ERR_DUPLICATE_OUTFALL_NUMBER, 409, "outfall_number already exists within this permit")

    outfall = base_entity("Outfall")
    outfall["id"] = str(uuid.uuid4())
    outfall.update(
        {
            "permit_id": permit["id"],
            "outfall_number": outfall_number,
            "description": body.get("description"),
            "status": "ACTIVE",
        }
    )
    db.outfalls[outfall["id"]] = outfall
    append_audit("Outfall", outfall["id"], "OUTFALL_CREATED", user_id, role)
    return success(serialize_outfall(outfall), 201)


@bp.route("/npdes/outfalls", methods=["GET"])
def list_outfalls():
    require_roles(["Any"])
    items = list(db.outfalls.values())
    permit_id = request.args.get("permit_id")
    if permit_id:
        items = [o for o in items if o["permit_id"] == permit_id]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_outfall(o) for o in page], total, limit, offset)


@bp.route("/npdes/outfalls/<oid>", methods=["GET"])
def get_outfall(oid):
    require_roles(["Any"])
    outfall = db.outfalls.get(oid)
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")
    return success(serialize_outfall(outfall), 200)


@bp.route("/npdes/outfalls/<oid>/deactivate", methods=["POST"])
def deactivate_outfall(oid):
    user_id, role = require_roles(["EnvironmentalManager"])
    outfall = db.outfalls.get(oid)
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")
    if outfall["status"] != "ACTIVE":
        raise err(ERR_OUTFALL_INACTIVE, 409, "Outfall is not ACTIVE")
    outfall["status"] = "INACTIVE"
    touch(outfall)
    cascade_outfall_deactivate(outfall, user_id, role)
    append_audit("Outfall", outfall["id"], "OUTFALL_DEACTIVATED", user_id, role)
    return success(serialize_outfall(outfall), 200)


@bp.route("/npdes/outfalls/<oid>/reactivate", methods=["POST"])
def reactivate_outfall(oid):
    user_id, role = require_roles(["EnvironmentalManager"])
    outfall = db.outfalls.get(oid)
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")
    if outfall["status"] != "INACTIVE":
        raise err(ERR_OUTFALL_NOT_INACTIVE, 409, "Outfall is not INACTIVE")
    permit = db.permits.get(outfall["permit_id"])
    if permit is None or permit["status"] != "ACTIVE":
        raise err(ERR_PERMIT_NOT_ACTIVE, 409, "Parent permit is not ACTIVE")
    outfall["status"] = "ACTIVE"
    touch(outfall)
    append_audit("Outfall", outfall["id"], "OUTFALL_REACTIVATED", user_id, role)
    return success(serialize_outfall(outfall), 200)
