"""Jurisdiction routes."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import require_roles
from response import success, parse_pagination, paginate


bp = Blueprint("jurisdictions", __name__)


@bp.route("/jurisdictions", methods=["POST"])
@require_roles("PlatformAdmin")
def create_jurisdiction():
    body = request.get_json(silent=True) or {}
    jid = new_id()
    j = {
        "id": jid,
        "created_at": now_iso(),
        "jurisdiction_code": body.get("jurisdiction_code"),
        "tax_rate_bps": int(body.get("tax_rate_bps", 0)),
        "rounding_mode": body.get("rounding_mode"),
    }
    store.jurisdictions[jid] = j
    return success(dict(j), status=201)


@bp.route("/jurisdictions", methods=["GET"])
@require_roles("PlatformAdmin", "BillingOperator")
def list_jurisdictions():
    limit, offset = parse_pagination(request.args)
    items = list(store.jurisdictions.values())
    items.sort(key=lambda j: j["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(j) for j in page], status=200,
                   pagination=meta, response_type="array")
