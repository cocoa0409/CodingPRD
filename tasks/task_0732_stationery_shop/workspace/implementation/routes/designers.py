"""Designer endpoints."""

from flask import Blueprint, request

import db
import middleware
import models
import response as resp
import util

bp = Blueprint("designers", __name__)


@bp.route("/designers", methods=["POST"])
def create_designer():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    full_name = util.get_str(body, "full_name")
    active = util.get_bool(body, "active", required=False, default=True)
    d = models.make_common({
        "full_name": full_name,
        "active": bool(active),
    })
    db.designers[d["id"]] = d
    return resp.created(d)


@bp.route("/designers/<did>", methods=["GET"])
def get_designer(did):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    d = models.get_designer(did)
    return resp.ok(d)


@bp.route("/designers", methods=["GET"])
def list_designers():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()
    active_filter = request.args.get("active")
    items = list(db.designers.values())
    if active_filter is not None:
        av = active_filter.lower()
        if av in ("true", "1"):
            items = [d for d in items if d["active"]]
        elif av in ("false", "0"):
            items = [d for d in items if not d["active"]]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
