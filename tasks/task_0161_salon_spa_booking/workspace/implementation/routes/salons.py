"""Salon routes: create, fetch, clock advance (PRD §3.1, §2.5, §2.7)."""
from flask import Blueprint

import db
from errors import err
from lookups import get_salon
from response import success
from util import stamp_create, touch, public, parse_dt
import validate as v
from routes.common import auth, json_body, ALL_ROLES

bp = Blueprint("salons", __name__)

TIP_POLICIES = {"DIRECT", "POOLED"}


@bp.post("/salons")
def create_salon():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    name = v.req_str(body, "name")
    timezone_ = v.opt_str(body, "timezone", default="UTC")
    no_show_fee_pct = v.opt_number(body, "no_show_fee_pct", default=0.50, minimum=0, maximum=1)
    no_show_suspend_threshold = v.opt_int(body, "no_show_suspend_threshold", default=3, minimum=1)
    tip_split_policy = v.opt_enum(body, "tip_split_policy", TIP_POLICIES, default="DIRECT")

    salon = {
        "name": name,
        "timezone": timezone_,
        "no_show_fee_pct": no_show_fee_pct,
        "no_show_suspend_threshold": no_show_suspend_threshold,
        "tip_split_policy": tip_split_policy,
    }
    stamp_create(salon)
    # current_utc initialized to created_at (PRD §2.5).
    salon["current_utc"] = salon["created_at"]
    db.salons[salon["id"]] = salon
    return success(public(salon), status=201)


@bp.get("/salons/<salon_id>")
def get_salon_route(salon_id):
    auth(ALL_ROLES)
    salon = get_salon(salon_id)
    return success(public(salon), status=200)


@bp.post("/salons/<salon_id>/_clock/advance")
def advance_clock(salon_id):
    auth(("SalonOwner",))
    salon = get_salon(salon_id)  # existence first (priority 3)
    body = json_body()
    v.require_object(body)

    to_iso = v.req_str(body, "to_iso8601")
    parse_dt(to_iso, "to_iso8601")  # validate format

    # OCC guard on Salon.version (priority 14 -> ERR_STALE_SALON_VERSION).
    if "expected_salon_version" not in body or body["expected_salon_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_salon_version is required")
    expected = v.req_int(body, "expected_salon_version")
    if expected != salon["version"]:
        raise err("ERR_STALE_SALON_VERSION", "salon version is stale")

    salon["current_utc"] = to_iso
    touch(salon)  # version +1
    return success(public(salon), status=200)
