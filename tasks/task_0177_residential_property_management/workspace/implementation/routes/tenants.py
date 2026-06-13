"""Tenant routes (PRD §3.11) — get, list. Tenants are minted by lease signing,
never created directly."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role
from response import object_response, array_response
from services.common import (
    serialize, parse_pagination, paginate, filter_param,
)

bp = Blueprint("tenants", __name__)


@bp.route("/tenants/<id>", methods=["GET"])
def get_tenant(id):
    require_role({"PropertyManager", "Tenant"})
    with db.LOCK:
        record = db.tenants.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Tenant not found")
        return object_response(serialize(record), 200)


@bp.route("/tenants", methods=["GET"])
def list_tenants():
    require_role({"PropertyManager"})
    applicant_id = filter_param(request.args, "applicant_id")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.tenants.values())
        if applicant_id is not None:
            records = [r for r in records if r["applicant_id"] == applicant_id]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
