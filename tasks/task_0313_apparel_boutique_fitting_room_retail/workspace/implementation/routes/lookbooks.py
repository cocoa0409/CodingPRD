"""Lookbooks: curated style collections (PRD §3.9)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_enum, parse_pagination, paginate,
    serialize, serialize_list,
)

bp = Blueprint("lookbooks", __name__)

SEASONS = {"SPRING", "SUMMER", "FALL", "WINTER"}
ALL_READ_ROLES = {"StoreManager", "Merchandiser", "StoreAssociate", "Customer"}


def _featured_count(style_ids):
    count = 0
    for sid in style_ids:
        st = db.styles.get(sid)
        if st is not None and not st["clearance"]:
            count += 1
    return count


def _validate_style_ids(value):
    if not isinstance(value, list):
        raise err(errors.ERR_INVALID_REQUEST, "style_ids must be an array")
    for sid in value:
        if not isinstance(sid, str):
            raise err(errors.ERR_INVALID_REQUEST, "style_ids must contain strings")
        get_or_404("style", sid)
    return value


@bp.post("/lookbooks")
def create_lookbook():
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    body = get_json_body()
    boutique_id = require_str(body, "boutique_id")
    title = require_str(body, "title")
    season = require_enum(body, "season", SEASONS)
    get_or_404("boutique", boutique_id)
    style_ids = body.get("style_ids", [])
    if style_ids is None:
        style_ids = []
    style_ids = _validate_style_ids(style_ids)

    rec = stamp_new({
        "boutique_id": boutique_id,
        "title": title,
        "season": season,
        "style_ids": list(style_ids),
        "status": "DRAFT",
        "featured_count": _featured_count(style_ids),
    })
    db.lookbooks[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/lookbooks/<rid>")
def get_lookbook(rid):
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    rec = get_or_404("lookbook", rid)
    return success(serialize(rec))


@bp.get("/lookbooks")
def list_lookbooks():
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.lookbooks.values())
    boutique_id = request.args.get("boutique_id")
    season = request.args.get("season")
    if boutique_id is not None:
        items = [l for l in items if l["boutique_id"] == boutique_id]
    if season is not None:
        items = [l for l in items if l["season"] == season]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.patch("/lookbooks/<rid>")
def patch_lookbook(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    lb = get_or_404("lookbook", rid)
    body = get_json_body()
    # Frozen check (priority 18).
    if lb["status"] == "PUBLISHED":
        raise err(errors.ERR_LOOKBOOK_FROZEN, "published lookbook is frozen")

    if "title" in body and body["title"] is not None:
        if not isinstance(body["title"], str) or body["title"] == "":
            raise err(errors.ERR_INVALID_REQUEST, "title must be a non-empty string")
        lb["title"] = body["title"]
    if "style_ids" in body and body["style_ids"] is not None:
        style_ids = _validate_style_ids(body["style_ids"])
        lb["style_ids"] = list(style_ids)

    lb["featured_count"] = _featured_count(lb["style_ids"])
    touch(lb)
    return success(serialize(lb))


@bp.post("/lookbooks/<rid>/publish")
def publish_lookbook(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    lb = get_or_404("lookbook", rid)
    if lb["status"] == "PUBLISHED":
        raise err(errors.ERR_LOOKBOOK_FROZEN, "published lookbook is frozen")
    lb["status"] = "PUBLISHED"
    touch(lb)
    return success(serialize(lb))
