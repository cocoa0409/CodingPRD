"""Technicians (PRD 3.6)."""

from flask import Blueprint, request

from common import get_body, stamp_new, serialize, paginate, as_int, as_str
from db import db
from lookups import get_technician
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("technicians", __name__)


@bp.route("/technicians", methods=["POST"])
def create_technician():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    body = get_body()
    name = as_str(body, "name")
    hourly_cost = as_int(body, "hourly_cost_cents", minimum=0)
    cleanup = as_int(body, "cleanup_buffer_minutes", required=False, default=30, minimum=0)
    rec = stamp_new({
        "name": name,
        "hourly_cost_cents": hourly_cost,
        "cleanup_buffer_minutes": cleanup,
    })
    db.technicians[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    items, limit, offset, total = paginate(list(db.technicians.values()))
    return ok_list(items, limit, offset, total)


@bp.route("/technicians/<tid>", methods=["GET"])
def get_technician_route(tid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    rec = get_technician(tid)
    return ok(serialize(rec), 200)
