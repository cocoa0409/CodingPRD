from __future__ import annotations
from flask import Blueprint, request

from db import db, stamp_common
from errors import raise_error, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean

bp = Blueprint("bundles", __name__)


@bp.route("/bundles", methods=["POST"])
@require_roles("StoreManager")
def create_bundle():
    body = get_body()
    bundle_code = require_field(body, "bundle_code")
    theme_tag = require_field(body, "theme_tag")
    bundle_price_cents = as_int(
        require_field(body, "bundle_price_cents"), "bundle_price_cents"
    )
    lines = require_field(body, "lines")

    if not isinstance(bundle_code, str) or not bundle_code:
        raise_error(ERR_INVALID_REQUEST, "bundle_code must be non-empty string")
    if bundle_price_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "bundle_price_cents must be >= 0")
    if not isinstance(lines, list) or not lines:
        raise_error(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    for existing in db.bundles.values():
        if existing["bundle_code"] == bundle_code:
            raise_error(ERR_INVALID_REQUEST, f"bundle_code '{bundle_code}' already exists")

    # Validate FKs before any write
    for ln in lines:
        if not isinstance(ln, dict):
            raise_error(ERR_INVALID_REQUEST, "each line must be an object")
        sku_id = ln.get("sku_id")
        qty = ln.get("qty")
        if sku_id is None or qty is None:
            raise_error(ERR_INVALID_REQUEST, "line requires sku_id and qty")
        if sku_id not in db.skus:
            raise_error(ERR_FK_NOT_FOUND, f"sku_id {sku_id} not found")
        qty_i = as_int(qty, "qty")
        if qty_i < 1:
            raise_error(ERR_INVALID_REQUEST, "qty must be >= 1")

    bundle = {
        "bundle_code": bundle_code,
        "theme_tag": theme_tag,
        "bundle_price_cents": bundle_price_cents,
        "status": "ACTIVE",
    }
    stamp_common(bundle)
    db.bundles[bundle["id"]] = bundle

    for ln in lines:
        bl = {
            "bundle_id": bundle["id"],
            "sku_id": ln["sku_id"],
            "qty": int(ln["qty"]),
        }
        stamp_common(bl)
        # BundleLine carries only id + created_at per PRD §2.4
        bl.pop("updated_at", None)
        bl.pop("version", None)
        db.bundle_lines[bl["id"]] = bl

    return created(clean(bundle))


@bp.route("/bundles/<id>", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def get_bundle(id):
    return ok(clean(fetch(db.bundles, id)))


@bp.route("/bundles/<id>/lines", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def bundle_lines(id):
    fetch(db.bundles, id)  # existence
    limit, offset = parse_limit_offset()
    items = [bl for bl in db.bundle_lines.values() if bl["bundle_id"] == id]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/bundle-lines", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def list_bundle_lines():
    limit, offset = parse_limit_offset()
    sku_id = request.args.get("sku_id")
    bundle_id = request.args.get("bundle_id")
    items = list(db.bundle_lines.values())
    if sku_id is not None:
        items = [b for b in items if b["sku_id"] == sku_id]
    if bundle_id is not None:
        items = [b for b in items if b["bundle_id"] == bundle_id]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/bundle-lines/<id>", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def get_bundle_line(id):
    return ok(clean(fetch(db.bundle_lines, id)))
