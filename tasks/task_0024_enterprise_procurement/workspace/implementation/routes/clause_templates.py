"""ClauseTemplate endpoints (PRD §3.6)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db, stamp_create, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from validate import get_json_body, require_enum, require_fields, require_string

bp = Blueprint("clause_templates", __name__)

CATEGORIES = {"PAYMENT", "DELIVERY", "WARRANTY", "IP", "CONFIDENTIALITY", "TERMINATION"}


@bp.post("/clause-templates")
@require_roles("LegalApprover")
def create_clause_template():
    body = get_json_body()
    require_fields(body, ["code", "title", "body", "category"])
    code = require_string(body["code"], "code")
    if any(t.get("code") == code for t in db.clause_templates.values()):
        raise err("ERR_VALIDATION", "code already exists.")
    title = require_string(body["title"], "title")
    body_text = require_string(body["body"], "body")
    category = body["category"]
    require_enum(category, CATEGORIES, "category")
    row = {
        "code": code,
        "title": title,
        "body": body_text,
        "category": category,
        "is_active": True,
    }
    stamp_create(row, common=True)
    db.clause_templates[row["id"]] = row
    return jsonify(success_object(serialize(row))), 201


@bp.get("/clause-templates")
@require_roles("LegalApprover", "Buyer")
def list_clause_templates():
    limit, offset = parse_limit_offset()
    cat = request.args.get("category")
    is_active = request.args.get("is_active")
    rows = list(db.clause_templates.values())
    if cat is not None:
        rows = [r for r in rows if r.get("category") == cat]
    if is_active is not None:
        flag = is_active.lower() in ("1", "true", "yes")
        rows = [r for r in rows if bool(r.get("is_active")) == flag]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200
