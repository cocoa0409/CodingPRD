"""Vendor endpoints (PRD §2.9, §3.7)."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_nonneg_int,
    invalid, parse_pagination, paginate, resolve,
)

bp = Blueprint("vendors", __name__)

# Non-terminal vendor statuses for tax_id uniqueness (BLOCKED is terminal).
NON_TERMINAL = {"APPROVED", "PROBATION"}


@bp.route("/procurement/vendors", methods=["POST"])
@require_roles("ProcurementAdmin")
def create_vendor():
    body = get_body()
    require_fields(body, ["name", "tax_id"])
    name = body["name"]
    tax_id = body["tax_id"]
    if not isinstance(name, str) or name == "":
        invalid("name must be a non-empty string")
    if not isinstance(tax_id, str) or tax_id == "":
        invalid("tax_id must be a non-empty string")

    grace_days = body.get("grace_days", 0)
    if grace_days is None:
        grace_days = 0
    require_nonneg_int(grace_days, "grace_days")

    # tax_id unique across non-terminal vendors.
    for v in db.vendors.values():
        if v["status"] in NON_TERMINAL and v["tax_id"] == tax_id:
            invalid("tax_id already in use by a non-terminal vendor")

    rec = {
        "name": name,
        "tax_id": tax_id,
        "grace_days": grace_days,
        "exception_count": 0,
        "status": "APPROVED",
    }
    init_common(rec)
    db.vendors[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/vendors/<vid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_vendor(vid):
    rec = resolve(db.vendors, vid)
    return object_response(public(rec))


@bp.route("/procurement/vendors", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vendors():
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = []
    for rec in db.vendors.values():
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/vendors/<vid>/block", methods=["POST"])
@require_roles("ProcurementAdmin")
def block_vendor(vid):
    rec = resolve(db.vendors, vid)
    rec["status"] = "BLOCKED"
    touch(rec)
    return object_response(public(rec))
