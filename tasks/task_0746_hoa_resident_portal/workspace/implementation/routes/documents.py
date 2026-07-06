"""Document upload/list/get — immutable."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso
from entities import new_document
from errors import raise_error
from response import success
from utils import (paginate, require_enum, require_fields, require_str,
                   require_json)

bp = Blueprint("documents", __name__)


@bp.route("/documents", methods=["POST"])
@require_role("HOAManager", "BoardMember")
def upload_document():
    body = require_json(request)
    require_fields(body, "title", "category", "content_url")
    title = require_str(body, "title")
    category = require_enum(body, "category", {"CCR", "POLICY", "MINUTES", "BUDGET"})
    content_url = require_str(body, "content_url")
    row = new_document(title, category, content_url, get_now_iso())
    db.documents[row["id"]] = row
    return success(row, status=201)


@bp.route("/documents", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def list_documents():
    cat = request.args.get("category")
    items = list(db.documents.values())
    if cat:
        items = [d for d in items if d["category"] == cat]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/documents/<did>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def get_document(did):
    d = db.documents.get(did)
    if not d:
        raise_error("ERR_NOT_FOUND", "document not found")
    return success(d)
