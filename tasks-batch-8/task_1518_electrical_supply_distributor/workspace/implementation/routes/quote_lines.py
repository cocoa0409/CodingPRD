"""QuoteLine endpoints (PRD §3.4)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from db import new_record, sort_key
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_QUOTE_NOT_FOUND,
    ERR_QUOTE_NOT_DRAFT,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_QUOTE_LINE_NOT_FOUND,
    ERR_BELOW_MIN_CUT,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_quote_line
from util import get_json_body, paginate, require_number, require_string

bp = Blueprint("quote_lines", __name__, url_prefix="/distributor")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


@bp.post("/quote-lines")
@require_roles("SalesRep")
@atomic
def create_quote_line():
    body = get_json_body()
    quote_id = require_string(body, "quote_id")
    catalog_item_id = require_string(body, "catalog_item_id")
    qty = require_number(body, "qty")
    if qty <= 0:
        raise_err(ERR_INVALID_REQUEST, "qty must be > 0")
    unit_price = require_number(body, "unit_price_cents")
    if unit_price < 0:
        raise_err(ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")

    quote = db.quotes.get(quote_id)
    if quote is None:
        raise_err(ERR_QUOTE_NOT_FOUND, "No quote with the given id")
    item = db.catalog_items.get(catalog_item_id)
    if item is None:
        raise_err(ERR_CATALOG_ITEM_NOT_FOUND, "No catalog item with the given id")

    # Lazy expiry applies to reads/transitions of the quote itself, not to
    # child-resource creation; the stored status governs the DRAFT check.
    if quote["status"] != "DRAFT":
        raise_err(ERR_QUOTE_NOT_DRAFT, "Adding a line requires the quote in DRAFT")
    if item["sell_uom"] == "FOOT" and qty < item["min_cut_ft"]:
        raise_err(ERR_BELOW_MIN_CUT, "FOOT line qty below the item's min_cut_ft")

    line = new_record(
        {
            "quote_id": quote_id,
            "catalog_item_id": catalog_item_id,
            "qty": qty,
            "unit_price_cents": unit_price,
        }
    )
    db.quote_lines[line["id"]] = line
    return success_object(ser_quote_line(line), 201)


@bp.get("/quote-lines")
@require_roles(*ROLES)
def list_quote_lines():
    quote_id = _query_arg("quote_id")
    catalog_item_id = _query_arg("catalog_item_id")
    items = sorted(db.quote_lines.values(), key=sort_key)
    if quote_id is not None:
        items = [l for l in items if l["quote_id"] == quote_id]
    if catalog_item_id is not None:
        items = [l for l in items if l["catalog_item_id"] == catalog_item_id]
    page, limit, offset, total = paginate(items)
    return success_list([ser_quote_line(l) for l in page], limit, offset, total)


@bp.get("/quote-lines/<line_id>")
@require_roles(*ROLES)
def get_quote_line(line_id: str):
    line = db.quote_lines.get(line_id)
    if line is None:
        raise_err(ERR_QUOTE_LINE_NOT_FOUND, "No quote line with the given id")
    return success_object(ser_quote_line(line))
