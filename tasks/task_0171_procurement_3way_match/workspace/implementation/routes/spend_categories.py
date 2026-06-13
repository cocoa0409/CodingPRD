"""SpendCategory endpoints (PRD §2.9, §3)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_nonneg_int,
    invalid, parse_pagination, paginate, resolve,
)

bp = Blueprint("spend_categories", __name__)


@bp.route("/procurement/spend-categories", methods=["POST"])
@require_roles("ProcurementAdmin")
def create_spend_category():
    body = get_body()
    require_fields(body, ["name", "code", "approval_threshold_cents",
                          "director_threshold_cents"])

    name = body["name"]
    code = body["code"]
    if not isinstance(name, str) or name == "":
        invalid("name must be a non-empty string")
    if not isinstance(code, str) or code == "":
        invalid("code must be a non-empty string")

    approval_threshold = body["approval_threshold_cents"]
    director_threshold = body["director_threshold_cents"]
    require_nonneg_int(approval_threshold, "approval_threshold_cents")
    require_nonneg_int(director_threshold, "director_threshold_cents")
    if director_threshold < approval_threshold:
        invalid("director_threshold_cents must be >= approval_threshold_cents")

    preferred_vendor_id = body.get("preferred_vendor_id")
    if preferred_vendor_id is not None:
        resolve(db.vendors, preferred_vendor_id)

    # Unique code across all non-archived categories.
    for cat in db.spend_categories.values():
        if cat["status"] != "ARCHIVED" and cat["code"] == code:
            invalid("code already in use by a non-archived category")

    rec = {
        "name": name,
        "code": code,
        "approval_threshold_cents": approval_threshold,
        "director_threshold_cents": director_threshold,
        "preferred_vendor_id": preferred_vendor_id,
        "status": "ACTIVE",
    }
    init_common(rec)
    db.spend_categories[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/spend-categories/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_spend_category(sid):
    rec = resolve(db.spend_categories, sid)
    return object_response(public(rec))


@bp.route("/procurement/spend-categories", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_spend_categories():
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    preferred_vendor_id = request.args.get("preferred_vendor_id")
    items = []
    for rec in db.spend_categories.values():
        if status is not None and rec["status"] != status:
            continue
        if preferred_vendor_id is not None and rec["preferred_vendor_id"] != preferred_vendor_id:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/spend-categories/<sid>/archive", methods=["POST"])
@require_roles("ProcurementAdmin")
def archive_spend_category(sid):
    rec = resolve(db.spend_categories, sid)
    rec["status"] = "ARCHIVED"
    touch(rec)
    return object_response(public(rec))
