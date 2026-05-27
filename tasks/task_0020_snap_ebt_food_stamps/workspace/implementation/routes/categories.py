"""EligibleItemCategory routes."""

import re
from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    get_json_body, require_nonempty_str, require_bool,
    parse_pagination, paginate, new_id,
)


bp = Blueprint("categories", __name__)

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


def _cat_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "code": c["code"],
        "name": c["name"],
        "eligible": c["eligible"],
        "created_at": c["created_at"],
    }


@bp.route("/snap/eligible-item-categories", methods=["POST"])
@require_roles("PolicyAdmin")
def create_category(**_):
    body = get_json_body()
    code = require_nonempty_str(body, "code")
    name = require_nonempty_str(body, "name")
    eligible = require_bool(body, "eligible")

    if not CODE_RE.match(code):
        raise_api("ERR_INVALID_REQUEST", "code must match ^[A-Z][A-Z0-9_]{1,31}$")
    for existing in db.eligible_categories.values():
        if existing["code"] == code:
            raise_api("ERR_INVALID_REQUEST", f"Category code {code} already exists")

    now = db.current_utc_iso()
    c = {
        "id": new_id(),
        "code": code,
        "name": name,
        "eligible": eligible,
        "created_at": now,
    }
    db.eligible_categories[c["id"]] = c
    return success(_cat_view(c), 201)


@bp.route("/snap/eligible-item-categories/<cat_id>", methods=["GET"])
@require_roles("PolicyAdmin", "Merchant", "Caseworker")
def get_category(cat_id, **_):
    c = db.eligible_categories.get(cat_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EligibleItemCategory not found")
    return success(_cat_view(c))


@bp.route("/snap/eligible-item-categories", methods=["GET"])
@require_roles("PolicyAdmin", "Merchant", "Caseworker")
def list_categories(**_):
    limit, offset = parse_pagination()
    eligible_filter = request.args.get("eligible")
    code_filter = request.args.get("code")

    rows = list(db.eligible_categories.values())
    if eligible_filter is not None:
        if eligible_filter.lower() == "true":
            rows = [r for r in rows if r["eligible"] is True]
        elif eligible_filter.lower() == "false":
            rows = [r for r in rows if r["eligible"] is False]
        else:
            raise_api("ERR_INVALID_REQUEST", "eligible must be true or false")
    if code_filter is not None:
        rows = [r for r in rows if r["code"] == code_filter]

    page, total = paginate(rows, limit, offset)
    return list_success([_cat_view(r) for r in page], limit, offset, total)
