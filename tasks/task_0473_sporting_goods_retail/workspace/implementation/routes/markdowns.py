"""Markdown routes: schedule, get, list/filter (PRD §3.2)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_int, as_str, as_enum
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404
from services import serializers, pricing
from clock import parse_iso8601

bp = Blueprint("markdowns", __name__)

MARKDOWN_KINDS = {"SEASONAL", "CLEARANCE"}


@bp.route("/markdowns", methods=["POST"])
@require_roles("PriceAdmin")
def create_markdown():
    body = get_body()
    sku_id = as_str(body, "sku_id", required=True)
    markdown_kind = as_enum(body, "markdown_kind", MARKDOWN_KINDS, required=True)
    percent_off = as_int(body, "percent_off", required=True)
    effective_from = as_str(body, "effective_from", required=True)
    effective_until = as_str(body, "effective_until", required=True)

    get_or_404(db.skus, sku_id)

    # Window + percent validity (priority 11, §3.2).
    try:
        eff_from = parse_iso8601(effective_from)
        eff_until = parse_iso8601(effective_until)
    except ValueError:
        raise errors.ApiError(errors.ERR_INVALID_MARKDOWN_WINDOW, 422,
                              "effective_from / effective_until must be valid ISO 8601")
    if not (1 <= percent_off <= 90) or not (eff_from < eff_until):
        raise errors.ApiError(errors.ERR_INVALID_MARKDOWN_WINDOW, 422,
                              "percent_off must be 1..90 and effective_from < effective_until")

    # Overlap (priority 12, §3.2): half-open windows; touching at a point is OK.
    for m in db.markdowns.values():
        if m["sku_id"] != sku_id:
            continue
        m_from = parse_iso8601(m["effective_from"])
        m_until = parse_iso8601(m["effective_until"])
        if eff_from < m_until and m_from < eff_until:
            raise errors.ApiError(errors.ERR_MARKDOWN_OVERLAP, 409,
                                  "Markdown window overlaps an existing markdown on this SKU")

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "sku_id": sku_id,
        "markdown_kind": markdown_kind,
        "percent_off": percent_off,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    db.markdowns[rid] = rec
    return success(serializers.markdown(rec), 201)


@bp.route("/markdowns/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "Customer")
def get_markdown(rid):
    rec = get_or_404(db.markdowns, rid)
    return success(serializers.markdown(rec), 200)


@bp.route("/markdowns", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "Customer")
def list_markdowns():
    limit, offset = parse_pagination()
    sku_id = request.args.get("sku_id")
    items = list(db.markdowns.values())
    if sku_id is not None:
        items = [m for m in items if m["sku_id"] == sku_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.markdown(m) for m in page], limit, offset, total)
