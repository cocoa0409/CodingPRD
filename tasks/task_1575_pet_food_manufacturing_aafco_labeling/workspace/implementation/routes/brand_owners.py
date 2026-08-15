"""BrandOwner endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import stamp_new, serialize, serialize_list

bp = Blueprint("brand_owners", __name__)


@bp.route("/brand-owners", methods=["POST"])
def create_brand_owner():
    require_roles("PlatformAdmin")
    body = get_json_body()
    legal_name = require_string(body, "legal_name", max_len=200)
    fein = require_string(body, "fein")
    contact_email = require_string(body, "contact_email", non_empty=False)

    if len(fein) != 9 or not fein.isdigit():
        raise errors.invalid_request("fein must be a 9-digit string")

    for bo in store.brand_owners.values():
        if bo["fein"] == fein:
            raise errors.duplicate_key("fein already registered")

    bo = {
        "legal_name": legal_name,
        "fein": fein,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "open_recall_count": 0,
        "complaint_score": 0,
    }
    stamp_new(bo)
    store.brand_owners[bo["id"]] = bo
    return success_object(serialize(bo), 201)


@bp.route("/brand-owners/<id>", methods=["GET"])
def get_brand_owner(id):
    require_roles("PlatformAdmin", "RegulatoryAffairs", "QualityAnalyst",
                  "QAApprover", "FormulationScientist")
    bo = store.brand_owners.get(id)
    if bo is None:
        raise errors.not_found("BrandOwner not found")
    return success_object(serialize(bo), 200)


@bp.route("/brand-owners", methods=["GET"])
def list_brand_owners():
    require_roles("PlatformAdmin", "RegulatoryAffairs", "QualityAnalyst",
                  "QAApprover", "FormulationScientist")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = sorted(store.brand_owners.values(),
                   key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [b for b in items if b["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/brand-owners/<id>/complaint-cases", methods=["GET"])
def list_brand_owner_complaint_cases(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    bo = store.brand_owners.get(id)
    if bo is None:
        raise errors.not_found("BrandOwner not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [c for c in store.complaint_cases.values() if c["brand_owner_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)
