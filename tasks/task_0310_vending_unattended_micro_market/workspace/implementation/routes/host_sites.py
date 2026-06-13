"""HostSite endpoints (PRD 3.1)."""
from flask import Blueprint

from common import (get_json_body, get_or_404, list_response, require_number,
                    require_str, require_enum, require_int)
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("host_sites", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/host-sites", methods=["POST"])
@require_roles("FieldOps")
def create_host_site():
    body = get_json_body()
    name = require_str(body, "name")
    contact_email = require_str(body, "contact_email")
    commission_model = require_enum(body, "commission_model", {"FLAT", "TIERED"},
                                    allow_missing=True, default="FLAT")
    flat_pct = require_number(body, "flat_commission_pct", allow_missing=True, default=0.10)
    guarantee = require_int(body, "monthly_guarantee_cents", allow_missing=True, default=0)

    obj = {
        "name": name,
        "contact_email": contact_email,
        "commission_model": commission_model,
        "flat_commission_pct": flat_pct,
        "monthly_guarantee_cents": guarantee,
        "lifetime_commission_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.host_sites[obj["id"]] = obj
    return object_response(serialize.host_site(obj), 201)


@bp.route("/operations/host-sites", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_host_sites():
    return list_response(list(db.host_sites.values()), serialize.host_site)


@bp.route("/operations/host-sites/<host_site_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_host_site(host_site_id):
    obj = get_or_404("host_sites", host_site_id)
    return object_response(serialize.host_site(obj))


@bp.route("/operations/host-sites/<host_site_id>/suspend", methods=["POST"])
@require_roles("FieldOps")
def suspend_host_site(host_site_id):
    obj = get_or_404("host_sites", host_site_id)
    obj["status"] = "SUSPENDED"
    touch(obj)
    return object_response(serialize.host_site(obj))
