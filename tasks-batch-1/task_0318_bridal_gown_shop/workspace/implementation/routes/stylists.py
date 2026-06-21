"""Stylist endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import common
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("stylists", __name__)


@bp.route("/stylists", methods=["POST"])
@require_roles("ShopManager")
def create_stylist():
    body = common.get_body()
    full_name = common.as_str(body, "full_name")
    buffer_minutes = common.as_int(
        body, "turnaround_buffer_minutes", minimum=0, required=False, default=15
    )
    active = common.as_bool(body, "active", required=False, default=True)
    obj = {
        "id": db.new_id(),
        "full_name": full_name,
        "turnaround_buffer_minutes": buffer_minutes,
        "active": active,
    }
    db.stamp_create(obj)
    db.stylists[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/stylists", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_stylists():
    limit, offset = common.paginate(request.args)
    window, meta = common.page_slice(list(db.stylists.values()), limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/stylists/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_stylist(sid):
    obj = services.get_stylist(sid)
    return success(common.serialize(obj))


@bp.route("/stylists/<sid>", methods=["PATCH"])
@require_roles("ShopManager")
def update_stylist(sid):
    obj = services.get_stylist(sid)
    body = common.get_body()
    changed = False
    if "full_name" in body and body["full_name"] is not None:
        obj["full_name"] = common.as_str(body, "full_name")
        changed = True
    if "turnaround_buffer_minutes" in body and body["turnaround_buffer_minutes"] is not None:
        obj["turnaround_buffer_minutes"] = common.as_int(
            body, "turnaround_buffer_minutes", minimum=0
        )
        changed = True
    if "active" in body and body["active"] is not None:
        obj["active"] = common.as_bool(body, "active")
        changed = True
    if changed:
        db.touch(obj)
    return success(common.serialize(obj))
