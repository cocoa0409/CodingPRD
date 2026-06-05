"""CapTable routes. PRD §3.1."""
from __future__ import annotations

from flask import Blueprint

import db
from common import (
    get_body, optional_int, pagination_params, paginate_and_sort,
    require_int, require_string, stamp_common_fields, touch,
)
from errors import APIError, ERR_INVALID_STATE, ERR_STALE_VERSION
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("cap_tables", __name__)


@bp.post("/cap-tables")
@require_roles("Administrator")
def create_cap_table():
    body = get_body()
    company_name = require_string(body, "company_name", max_len=200, non_empty=True)
    authorized_shares = require_int(body, "authorized_shares", strict_positive=True)
    now = db.now_utc()
    ct = {
        "company_name": company_name,
        "authorized_shares": authorized_shares,
        "status": "OPEN",
        "issued_shares": 0,
        "fully_diluted_shares": 0,
        "locked_at": None,
    }
    stamp_common_fields(ct, now)
    db.cap_tables[ct["id"]] = ct
    return created(core.serialize_cap_table(ct))


@bp.get("/cap-tables/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_cap_table(cid):
    ct = core.get_cap_table(cid)
    return success(core.serialize_cap_table(ct))


@bp.get("/cap-tables")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_cap_tables():
    limit, offset = pagination_params()
    items = list(db.cap_tables.values())
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize_cap_table(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )


def _check_occ(ct, body, field):
    expected = body.get(field)
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError(ERR_STALE_VERSION, f"{field} mismatch.", 412)
    if expected != ct["version"]:
        raise APIError(ERR_STALE_VERSION, f"{field} does not match current version.", 412)


@bp.post("/cap-tables/<cid>/lock")
@require_roles("BoardApprover")
def lock_cap_table(cid):
    ct = core.get_cap_table(cid)
    body = get_body()
    if ct["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, "Cap table must be OPEN to lock.", 409)
    _check_occ(ct, body, "expected_cap_table_version")
    now = db.now_utc()
    ct["status"] = "LOCKED"
    ct["locked_at"] = now
    touch(ct, now)
    return success(core.serialize_cap_table(ct))


@bp.post("/cap-tables/<cid>/unlock")
@require_roles("BoardApprover")
def unlock_cap_table(cid):
    ct = core.get_cap_table(cid)
    body = get_body()
    if ct["status"] != "LOCKED":
        raise APIError(ERR_INVALID_STATE, "Cap table must be LOCKED to unlock.", 409)
    _check_occ(ct, body, "expected_cap_table_version")
    now = db.now_utc()
    ct["status"] = "OPEN"
    ct["locked_at"] = None
    touch(ct, now)
    return success(core.serialize_cap_table(ct))


@bp.post("/cap-tables/<cid>/dissolve")
@require_roles("BoardApprover")
def dissolve_cap_table(cid):
    ct = core.get_cap_table(cid)
    if ct["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, "Cap table must be OPEN to dissolve.", 409)
    for g in core.grants_of(cid):
        if g["status"] == "ACTIVE":
            raise APIError(
                ERR_INVALID_STATE,
                "Cannot dissolve while an option grant is ACTIVE.",
                409,
            )
    now = db.now_utc()
    ct["status"] = "DISSOLVED"
    touch(ct, now)
    return success(core.serialize_cap_table(ct))
