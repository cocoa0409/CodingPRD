"""Buildings: create, list, get."""

from flask import Blueprint

import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from validate import (
    get_body, require_string, parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("buildings", __name__)


def _view(b):
    return {
        "id": b["id"],
        "site_id": b["site_id"],
        "name": b["name"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.route("/buildings", methods=["POST"])
def create_building():
    require_roles("OperatorAdmin")
    body = get_body()
    site_id = require_string(body, "site_id")
    name = require_string(body, "name")
    if db.sites.get(site_id) is None:
        raise err("ERR_SITE_NOT_FOUND")
    now = db.now_ts()
    b = {
        "id": db.new_id(),
        "site_id": site_id,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.buildings[b["id"]] = b
    return success_object(_view(b), status=201)


@bp.route("/buildings", methods=["GET"])
def list_buildings():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.buildings.values())
    site_f = get_filter("site_id")
    if site_f is not None:
        items = [b for b in items if b["site_id"] == site_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(b) for b in page], total, limit, offset)


@bp.route("/buildings/<bid>", methods=["GET"])
def get_building(bid):
    get_auth()
    b = db.buildings.get(bid)
    if b is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(b))
