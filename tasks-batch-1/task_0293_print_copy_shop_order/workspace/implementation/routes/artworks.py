"""Artwork upload, preflight, and revise routes (PRD §3.3)."""

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services import pricing
from services.ownership import require_order_owner
from services.common import (
    get_body, require_fields, require_int, require_str, lookup, list_collection,
)

bp = Blueprint("artworks", __name__)


@bp.post("/artworks")
@require_roles("ShopStaff", "Customer")
def create_artwork():
    body = get_body()
    require_fields(body, "order_line_id", "file_name", "page_count", "dpi", "bleed_mm")
    order_line_id = require_str(body, "order_line_id")
    line = lookup(db.order_lines, order_line_id)
    # Customer upload acts on own order's line.
    order = db.orders.get(line["order_id"])
    if order is not None:
        require_order_owner(order)

    file_name = require_str(body, "file_name")
    page_count = require_int(body, "page_count", min_value=1)
    dpi = require_int(body, "dpi", min_value=1)
    bleed_mm = _require_number(body, "bleed_mm", min_value=0)

    rec = {
        "order_line_id": order_line_id,
        "file_name": file_name,
        "page_count": page_count,
        "dpi": dpi,
        "bleed_mm": bleed_mm,
        "preflight_status": "UPLOADED",
        "preflight_reason": None,
    }
    db.stamp_new(rec)
    db.artworks[rec["id"]] = rec
    return object_response(serialize.artwork(rec), 201)


@bp.get("/artworks")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_artworks():
    order_line_id = request.args.get("order_line_id")
    items, limit, offset, total = list_collection(
        db.artworks,
        (lambda r: r["order_line_id"] == order_line_id) if order_line_id else None)
    return array_response([serialize.artwork(r) for r in items], limit, offset, total)


@bp.get("/artworks/<artwork_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_artwork(artwork_id):
    rec = lookup(db.artworks, artwork_id)
    return object_response(serialize.artwork(rec), 200)


@bp.patch("/artworks/<artwork_id>")
@require_roles("Customer")
def revise_artwork(artwork_id):
    art = lookup(db.artworks, artwork_id)
    line = lookup(db.order_lines, art["order_line_id"])
    order = db.orders.get(line["order_id"])
    if order is not None:
        require_order_owner(order)

    # Only a FAILED artwork may be revised (FAILED -> UPLOADED) (PRD §3.3).
    if art["preflight_status"] != "FAILED":
        raise err(errors.ERR_INVALID_STATE,
                  "Only a FAILED artwork may be revised")

    body = get_body()
    if "page_count" in body and body["page_count"] is not None:
        art["page_count"] = require_int(body, "page_count", min_value=1)
    if "dpi" in body and body["dpi"] is not None:
        art["dpi"] = require_int(body, "dpi", min_value=1)
    if "bleed_mm" in body and body["bleed_mm"] is not None:
        art["bleed_mm"] = _require_number(body, "bleed_mm", min_value=0)

    art["preflight_status"] = "UPLOADED"
    art["preflight_reason"] = None
    db.touch(art)
    return object_response(serialize.artwork(art), 200)


@bp.post("/artworks/<artwork_id>/preflight")
@require_roles("ProductionOperator")
def run_preflight(artwork_id):
    art = lookup(db.artworks, artwork_id)
    # Running preflight on a file not in UPLOADED -> ERR_INVALID_STATE (409).
    if art["preflight_status"] != "UPLOADED":
        raise err(errors.ERR_INVALID_STATE,
                  "Preflight can only run on an UPLOADED artwork")

    # Pinned check order: DPI before bleed (PRD §3.3).
    if art["dpi"] < pricing.MIN_DPI:
        art["preflight_status"] = "FAILED"
        art["preflight_reason"] = "DPI %s below minimum %s" % (art["dpi"], pricing.MIN_DPI)
    elif art["bleed_mm"] < pricing.MIN_BLEED_MM:
        art["preflight_status"] = "FAILED"
        art["preflight_reason"] = ("Bleed %smm below minimum %smm"
                                   % (art["bleed_mm"], pricing.MIN_BLEED_MM))
    else:
        art["preflight_status"] = "PASSED"
        art["preflight_reason"] = None
    db.touch(art)

    # On PASS, the line advances OPEN -> PREFLIGHT_OK (PRD §3.3).
    if art["preflight_status"] == "PASSED":
        line = db.order_lines.get(art["order_line_id"])
        if line is not None and line["status"] == "OPEN":
            line["status"] = "PREFLIGHT_OK"
            db.touch(line)

    return object_response(serialize.artwork(art), 200)


def _require_number(body, name, *, min_value=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_VALIDATION, "Field %s must be a number" % name)
    if min_value is not None and val < min_value:
        raise err(errors.ERR_VALIDATION, "Field %s must be >= %s" % (name, min_value))
    return val
