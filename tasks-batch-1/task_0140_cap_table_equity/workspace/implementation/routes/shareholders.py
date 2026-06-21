"""Shareholder routes. PRD §3.3."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_bool,
    require_enum, require_string, stamp_common_fields,
)
from errors import APIError, ERR_VALIDATION
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("shareholders", __name__)

_HOLDER_TYPES = {"FOUNDER", "EMPLOYEE", "INVESTOR", "ENTITY"}


@bp.post("/shareholders")
@require_roles("Administrator")
def create_shareholder():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)  # existence (ERR_NOT_FOUND)
    legal_name = require_string(body, "legal_name", non_empty=True)
    holder_type = require_enum(body, "holder_type", _HOLDER_TYPES)
    email = require_string(body, "email", non_empty=True)
    is_us_taxpayer = require_bool(body, "is_us_taxpayer", default=True)

    for s in db.shareholders.values():
        if s["cap_table_id"] == cap_table_id and s["email"] == email:
            raise APIError(ERR_VALIDATION, "email must be unique within the cap table.", 400)

    now = db.now_utc()
    sh = {
        "cap_table_id": cap_table_id,
        "legal_name": legal_name,
        "holder_type": holder_type,
        "email": email,
        "is_us_taxpayer": is_us_taxpayer,
    }
    stamp_common_fields(sh, now)
    db.shareholders[sh["id"]] = sh
    return created(core.serialize(sh))


@bp.get("/shareholders/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_shareholder(cid):
    sh = core.get_shareholder(cid)
    return success(core.serialize(sh))


@bp.get("/shareholders")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_shareholders():
    limit, offset = pagination_params()
    items = list(db.shareholders.values())
    cap_table_id = request.args.get("cap_table_id")
    if cap_table_id is not None:
        items = [s for s in items if s["cap_table_id"] == cap_table_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(s) for s in page],
        limit=limit, offset=offset, total_count=total,
    )
