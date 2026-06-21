"""ShareIssuance routes (append-only). PRD §3.3."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_int,
    require_string, stamp_immutable,
)
from errors import (
    APIError, ERR_NOT_FOUND, ERR_TABLE_NOT_OPEN, ERR_AUTHORIZED_EXCEEDED, ERR_VALIDATION,
)
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("share_issuances", __name__)


@bp.post("/share-issuances")
@require_roles("Administrator")
def create_share_issuance():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    ct = core.get_cap_table(cap_table_id)
    security_class_id = require_string(body, "security_class_id")
    sc = core.get_security_class(security_class_id)
    shareholder_id = require_string(body, "shareholder_id")
    sh = core.get_shareholder(shareholder_id)
    share_count = require_int(body, "share_count", strict_positive=True)
    price_paid_cents = require_int(body, "price_paid_cents", min_value=0)

    # cross-aggregate referential consistency: class & shareholder on same table
    if sc["cap_table_id"] != cap_table_id:
        raise APIError(ERR_NOT_FOUND, "SecurityClass not found.", 404)
    if sh["cap_table_id"] != cap_table_id:
        raise APIError(ERR_NOT_FOUND, "Shareholder not found.", 404)

    # table must be OPEN (priority 12)
    if ct["status"] != "OPEN":
        raise APIError(ERR_TABLE_NOT_OPEN, "Cap table is not OPEN.", 409)

    # authorized not exceeded (priority 14)
    current_issued = core.compute_issued_shares(cap_table_id)
    if current_issued + share_count > ct["authorized_shares"]:
        raise APIError(ERR_AUTHORIZED_EXCEEDED, "Issuance would exceed authorized shares.", 422)

    now = db.now_utc()
    issuance = {
        "cap_table_id": cap_table_id,
        "security_class_id": security_class_id,
        "shareholder_id": shareholder_id,
        "share_count": share_count,
        "price_paid_cents": price_paid_cents,
        "issued_at": now,
    }
    stamp_immutable(issuance, now)
    db.share_issuances[issuance["id"]] = issuance

    # cascade: class shares_outstanding += share_count; recompute ledger; bump table version
    sc["shares_outstanding"] += share_count
    from common import touch
    touch(sc, now)
    core.recompute_ledger(ct, now, bump=True)

    return created(core.serialize(issuance))


@bp.get("/share-issuances/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor")
def get_share_issuance(cid):
    iss = db.share_issuances.get(cid)
    if iss is None:
        raise APIError(ERR_NOT_FOUND, "ShareIssuance not found.", 404)
    return success(core.serialize(iss))


@bp.get("/share-issuances")
@require_roles("Administrator", "BoardApprover", "Auditor")
def list_share_issuances():
    limit, offset = pagination_params()
    items = list(db.share_issuances.values())
    for key in ("cap_table_id", "security_class_id", "shareholder_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )
