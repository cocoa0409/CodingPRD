"""Keg tap endpoints (PRD §3.8)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create
from errors import ApiError, ERR_NOT_A_KEG, ERR_LINE_OVERLAP, invalid_request
from middleware import require_roles
from response import object_response, array_response
from routes.lookup import get_product
from validate import (get_json_body, require, as_int, parse_pagination, paginate)
from timeutil import parse_iso

bp = Blueprint("keg_taps", __name__)


@bp.route("/keg-taps", methods=["POST"])
@require_roles("BarManager", "InventoryManager")
def create_keg_tap():
    body = get_json_body()
    product_id = require(body, "product_id")
    draft_line_no = as_int(require(body, "draft_line_no"), "draft_line_no", ge=1)
    tapped_from_raw = require(body, "tapped_from")
    tapped_until_raw = require(body, "tapped_until")
    tapped_from = parse_iso(tapped_from_raw, "tapped_from")
    tapped_until = parse_iso(tapped_until_raw, "tapped_until")
    # tapped_until must be >= tapped_from
    if not (tapped_until >= tapped_from):
        raise invalid_request("tapped_until must be at or after tapped_from.")
    # body FK existence (404)
    product = get_product(product_id)
    # container_type must be KEG
    if product["container_type"] != "KEG":
        raise ApiError(ERR_NOT_A_KEG, 422, "Only a KEG product can be tapped onto a draft line.")

    # overlap check on the same draft_line_no. Closed intervals [a,b] and [c,d]
    # overlap iff a < d and c < b (strict); touching endpoints (b == c or d == a)
    # are permitted (PRD §3.8).
    for tap in db.keg_taps.values():
        if tap["draft_line_no"] != draft_line_no:
            continue
        a, b = tapped_from, tapped_until
        c, d = tap["_tapped_from_dt"], tap["_tapped_until_dt"]
        if a < d and c < b:
            raise ApiError(ERR_LINE_OVERLAP, 422,
                           "Tap interval overlaps an existing tap on the same draft line.")

    record = {
        "product_id": product_id,
        "draft_line_no": draft_line_no,
        "tapped_from": tapped_from_raw,
        "tapped_until": tapped_until_raw,
        "_tapped_from_dt": tapped_from,
        "_tapped_until_dt": tapped_until,
    }
    stamp_create(record)
    db.keg_taps[record["id"]] = record
    return object_response(serialize.keg_tap(record), 201)


@bp.route("/keg-taps", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def list_keg_taps():
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    draft_line_no = request.args.get("draft_line_no")
    items = list(db.keg_taps.values())
    if product_id is not None:
        items = [t for t in items if t["product_id"] == product_id]
    if draft_line_no is not None:
        try:
            dln = int(draft_line_no)
        except (ValueError, TypeError):
            raise invalid_request("draft_line_no must be an integer.")
        items = [t for t in items if t["draft_line_no"] == dln]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.keg_tap(t) for t in page], limit, offset, total)
