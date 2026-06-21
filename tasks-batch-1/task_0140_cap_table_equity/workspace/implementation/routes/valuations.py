"""Valuation routes. PRD §3.4."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_datetime,
    require_int, require_string, stamp_common_fields, touch,
)
from errors import (
    APIError, ERR_INVALID_STATE, ERR_VALUATION_WINDOW_OVERLAP, ERR_VALIDATION,
)
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("valuations", __name__)


def _closed_overlap(a_start, a_end, b_start, b_end) -> bool:
    """CLOSED intervals [a_start,a_end] vs [b_start,b_end]: touching conflicts."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/valuations")
@require_roles("Administrator")
def create_valuation():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    fmv = require_int(body, "fmv_per_share_cents", strict_positive=True)
    valuation_date = require_datetime(body, "valuation_date")
    expires_at = require_datetime(body, "expires_at")

    # closed-interval overlap vs any non-SUPERSEDED valuation (priority 15)
    for v in core.valuations_of(cap_table_id):
        if v["status"] == "SUPERSEDED":
            continue
        if _closed_overlap(valuation_date, expires_at, v["valuation_date"], v["expires_at"]):
            raise APIError(
                ERR_VALUATION_WINDOW_OVERLAP,
                "Valuation safe-harbor window overlaps an existing non-superseded valuation.",
                409,
            )

    now = db.now_utc()
    val = {
        "cap_table_id": cap_table_id,
        "fmv_per_share_cents": fmv,
        "valuation_date": valuation_date,
        "expires_at": expires_at,
        "status": "DRAFT",
        "superseded_by_id": None,
    }
    stamp_common_fields(val, now)
    db.valuations[val["id"]] = val
    return created(core.serialize(val))


@bp.get("/valuations/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor")
def get_valuation(cid):
    return success(core.serialize(core.get_valuation(cid)))


@bp.get("/valuations")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_valuations():
    limit, offset = pagination_params()
    items = list(db.valuations.values())
    cap_table_id = request.args.get("cap_table_id")
    superseded_by_id = request.args.get("superseded_by_id")
    if cap_table_id is not None:
        items = [v for v in items if v["cap_table_id"] == cap_table_id]
    if superseded_by_id is not None:
        items = [v for v in items if v.get("superseded_by_id") == superseded_by_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(v) for v in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/valuations/<cid>/approve")
@require_roles("BoardApprover")
def approve_valuation(cid):
    val = core.get_valuation(cid)
    ct = core.get_cap_table(val["cap_table_id"])
    if val["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Valuation must be DRAFT to approve.", 409)
    if ct["status"] == "DISSOLVED":
        raise APIError(ERR_INVALID_STATE, "Cap table is DISSOLVED.", 409)

    now = db.now_utc()
    # cascade: prior EFFECTIVE valuation -> SUPERSEDED
    for other in core.valuations_of(val["cap_table_id"]):
        if other["id"] != val["id"] and other["status"] == "EFFECTIVE":
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = val["id"]
            touch(other, now)

    val["status"] = "EFFECTIVE"
    touch(val, now)
    # recompute fully_diluted (notes re-price) + bump table version
    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize(val))
