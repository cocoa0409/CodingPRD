"""Permit endpoints."""

import uuid
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PERMIT_NOT_FOUND,
    ERR_DUPLICATE_PERMIT_NUMBER,
    ERR_PERMIT_NOT_IN_DRAFT,
    ERR_PERMIT_NOT_ISSUABLE,
    ERR_PERMIT_NO_OUTFALL,
    ERR_OUTFALL_NO_ACTIVE_LIMIT,
    ERR_PERMIT_NOT_ACTIVE,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_permit,
    paginate,
    cascade_permit_shutdown,
)

bp = Blueprint("permits", __name__)


@bp.route("/npdes/permits", methods=["POST"])
def create_permit():
    user_id, role = require_roles(["EnvironmentalManager"])
    body = get_body()
    require_fields(
        body,
        ["permit_number", "facility_name", "receiving_water_body", "effective_date", "expiration_date"],
    )
    permit_number = body["permit_number"]
    if not isinstance(permit_number, str) or not permit_number:
        raise err(ERR_INVALID_REQUEST, 400, "permit_number must be a non-empty string")
    effective_date = parse_iso(body["effective_date"], "effective_date")
    expiration_date = parse_iso(body["expiration_date"], "expiration_date")
    if expiration_date <= effective_date:
        raise err(ERR_INVALID_REQUEST, 400, "expiration_date must be strictly after effective_date")

    for p in db.permits.values():
        if p["permit_number"] == permit_number:
            raise err(ERR_DUPLICATE_PERMIT_NUMBER, 409, "permit_number already exists")

    permit = base_entity("Permit")
    permit["id"] = str(uuid.uuid4())
    permit.update(
        {
            "permit_number": permit_number,
            "facility_name": body["facility_name"],
            "receiving_water_body": body["receiving_water_body"],
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "status": "DRAFT",
            "superseded_by_permit_id": None,
            "compliance_posture": "GOOD_STANDING",
            "open_corrective_action_count": 0,
            "open_exceedance_count": 0,
        }
    )
    db.permits[permit["id"]] = permit
    append_audit("Permit", permit["id"], "PERMIT_CREATED", user_id, role)
    return success(serialize_permit(permit), 201)


@bp.route("/npdes/permits", methods=["GET"])
def list_permits():
    require_roles(["Any"])
    items = list(db.permits.values())
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    superseded_by = request.args.get("superseded_by_permit_id")
    if superseded_by:
        items = [p for p in items if p.get("superseded_by_permit_id") == superseded_by]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_permit(p) for p in page], total, limit, offset)


@bp.route("/npdes/permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles(["Any"])
    permit = db.permits.get(pid)
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    return success(serialize_permit(permit), 200)


@bp.route("/npdes/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    user_id, role = require_roles(["EnvironmentalManager"])
    permit = db.permits.get(pid)
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    if permit["status"] != "DRAFT":
        raise err(ERR_PERMIT_NOT_IN_DRAFT, 409, "Permit is not in DRAFT")
    now = db.clock.now()
    if not (permit["effective_date"] <= now < permit["expiration_date"]):
        raise err(ERR_PERMIT_NOT_ISSUABLE, 409, "Clock is outside [effective_date, expiration_date)")
    active_outfalls = [
        o for o in db.outfalls.values() if o["permit_id"] == pid and o["status"] == "ACTIVE"
    ]
    if len(active_outfalls) == 0:
        raise err(ERR_PERMIT_NO_OUTFALL, 409, "Permit has no ACTIVE outfall")
    for o in active_outfalls:
        has_limit = any(
            l for l in db.effluent_limits.values()
            if l["outfall_id"] == o["id"] and l["status"] == "ACTIVE"
        )
        if not has_limit:
            raise err(
                ERR_OUTFALL_NO_ACTIVE_LIMIT,
                409,
                f"Outfall {o['id']} has no ACTIVE effluent limit",
            )
    permit["status"] = "ACTIVE"
    touch(permit)
    append_audit("Permit", permit["id"], "PERMIT_ISSUED", user_id, role)
    return success(serialize_permit(permit), 200)


@bp.route("/npdes/permits/<pid>/terminate", methods=["POST"])
def terminate_permit(pid):
    user_id, role = require_roles(["EnvironmentalManager"])
    permit = db.permits.get(pid)
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    if permit["status"] != "ACTIVE":
        raise err(ERR_PERMIT_NOT_ACTIVE, 409, "Permit is not ACTIVE")
    permit["status"] = "TERMINATED"
    touch(permit)
    cascade_permit_shutdown(permit, user_id, role)
    append_audit("Permit", permit["id"], "PERMIT_TERMINATED", user_id, role)
    return success(serialize_permit(permit), 200)
