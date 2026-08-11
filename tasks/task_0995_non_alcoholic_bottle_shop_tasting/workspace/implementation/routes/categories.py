"""Category endpoints."""
from flask import Blueprint

import db as _db
from db import db, new_entity, touch
from errors import duplicate, not_found
from helpers import (body, get_or_404, opt_bool, paginate, pagination_params,
                     public, req_enum, req_str)
from middleware import require
from response import success

bp = Blueprint("categories", __name__)

COMPLIANCE_CLASSES = {"STANDARD", "SENSITIVE_INGREDIENT", "HEMP_DERIVED",
                      "KAVA", "FUNCTIONAL_MUSHROOM"}
READ_ROLES = ["PlatformAdmin", "ShopStaff", "Member", "Anonymous"]


@bp.post("/categories")
def create_category():
    require(["PlatformAdmin", "ShopStaff"])
    data = body()
    code = req_str(data, "code", min_len=2, max_len=48,
                   pattern=r"[a-z0-9-]+")
    display_name = req_str(data, "display_name")
    compliance_class = req_enum(data, "compliance_class", COMPLIANCE_CLASSES)
    active = opt_bool(data, "active", True)
    for cat in db["categories"].values():
        if cat["code"] == code:
            raise duplicate("Category code already exists")
    ent = new_entity({
        "code": code,
        "display_name": display_name,
        "compliance_class": compliance_class,
        "active": active,
    })
    db["categories"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/categories")
def list_categories():
    require(READ_ROLES)
    limit, offset = pagination_params()
    active = request_args_active()
    items = list(db["categories"].values())
    if active is not None:
        items = [c for c in items if c["active"] == active]
    page, pg = paginate(items, limit, offset)
    return success([public(c) for c in page], response_type="array",
                   pagination=pg)


def request_args_active():
    from helpers import parse_bool_param
    return parse_bool_param("active")


@bp.get("/categories/<cid>")
def get_category(cid):
    require(READ_ROLES)
    ent = get_or_404(db["categories"], cid)
    return success(public(ent))


@bp.get("/categories/<cid>/skus")
def category_skus(cid):
    require(READ_ROLES)
    get_or_404(db["categories"], cid)
    limit, offset = pagination_params()
    items = [s for s in db["skus"].values() if s["category_id"] == cid]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)
