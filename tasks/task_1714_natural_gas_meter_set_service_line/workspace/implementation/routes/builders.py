"""Builder endpoints."""

from flask import Blueprint, request

import db
from errors import ERR_INVALID_REQUEST, raise_error
from middleware import (
    ANY_ROLE,
    get_body,
    new_id,
    paginate,
    require_enum,
    require_fields,
    require_roles,
    require_str,
)
from response import success_list, success_object
from services.domain import get_builder, touch

bp = Blueprint("builders", __name__)


@bp.route("/builders", methods=["POST"])
def create_builder():
    require_roles("NewBusinessRep", "SystemAdmin")
    body = get_body()
    require_fields(body, "company_name", "contact_email", "license_number")
    now = db.now_iso()
    builder = {
        "id": new_id(),
        "company_name": require_str(body, "company_name"),
        "contact_email": require_str(body, "contact_email"),
        "license_number": require_str(body, "license_number"),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.builders[builder["id"]] = builder
    return success_object(builder, 201)


@bp.route("/builders/<bid>", methods=["GET"])
def get_one_builder(bid):
    require_roles(*ANY_ROLE)
    return success_object(get_builder(bid))


@bp.route("/builders", methods=["GET"])
def list_builders():
    require_roles(*ANY_ROLE)
    records = list(db.builders.values())
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/builders/<bid>", methods=["PATCH"])
def patch_builder(bid):
    require_roles("SystemAdmin")
    builder = get_builder(bid)
    body = get_body()
    require_fields(body, "status")
    status = require_enum(body, "status", ("ACTIVE", "SUSPENDED"))
    builder["status"] = status
    touch(builder)
    return success_object(builder)
