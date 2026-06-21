"""OptionPool routes. PRD §3.5."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_int,
    require_string, stamp_common_fields, touch,
)
from errors import APIError, ERR_INVALID_STATE, ERR_STALE_VERSION
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("option_pools", __name__)


@bp.post("/option-pools")
@require_roles("Administrator")
def create_option_pool():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    authorized_shares = require_int(body, "authorized_shares", strict_positive=True)
    now = db.now_utc()
    pool = {
        "cap_table_id": cap_table_id,
        "authorized_shares": authorized_shares,
        "allocated_shares": 0,
        "available_shares": authorized_shares,
        "status": "ACTIVE",
    }
    stamp_common_fields(pool, now)
    db.option_pools[pool["id"]] = pool
    return created(core.serialize(pool))


@bp.get("/option-pools/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor")
def get_option_pool(cid):
    pool = core.get_option_pool(cid)
    return success(core.serialize_pool(pool))


@bp.get("/option-pools")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_option_pools():
    limit, offset = pagination_params()
    items = list(db.option_pools.values())
    cap_table_id = request.args.get("cap_table_id")
    if cap_table_id is not None:
        items = [p for p in items if p["cap_table_id"] == cap_table_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize_pool(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/option-pools/<cid>/refresh")
@require_roles("BoardApprover")
def refresh_option_pool(cid):
    pool = core.get_option_pool(cid)
    body = get_body()
    # OCC check first: PRD §2.6 narrates the canonical pool case as "a grant
    # approval that exhausts the pool bumps its version, so a refresh carrying a
    # stale value ... is rejected" — i.e. the same action that bumps the version
    # also flips the pool out of ACTIVE, so the stale-version check must pre-empt
    # the ACTIVE-state gate for that scenario to surface as ERR_STALE_VERSION.
    expected = body.get("expected_pool_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) \
            or expected != pool["version"]:
        raise APIError(ERR_STALE_VERSION, "expected_pool_version does not match current version.", 412)
    if pool["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Pool must be ACTIVE to refresh.", 409)
    refresh_increment_shares = require_int(body, "refresh_increment_shares", min_value=0)

    now = db.now_utc()
    core.refresh_pool_totals(pool)
    old_available = pool["available_shares"]

    pool["status"] = "CLOSED"
    touch(pool, now)

    new_pool = {
        "cap_table_id": pool["cap_table_id"],
        "authorized_shares": old_available + refresh_increment_shares,
        "allocated_shares": 0,
        "available_shares": old_available + refresh_increment_shares,
        "status": "ACTIVE",
    }
    stamp_common_fields(new_pool, now)
    db.option_pools[new_pool["id"]] = new_pool
    return created(core.serialize(new_pool))
