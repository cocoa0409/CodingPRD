"""Caregiver endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record, touch
from services.lookup import get_caregiver, sorted_by_created
from services.serialize import caregiver_out

bp = Blueprint("caregivers", __name__)

AVAILABILITY = {"AVAILABLE", "BUSY", "OFFLINE", "SUSPENDED"}


@bp.route("/marketplace/caregivers", methods=["POST"])
def create_caregiver():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    body = get_json()

    full_name = v.req_str(body, "full_name")
    email = v.req_str(body, "email")
    floor = v.req_int(body, "hourly_rate_floor_cents", minimum=1)

    rec = base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "hourly_rate_floor_cents": floor,
        "background_check_tier": "NONE",
        "verification_status": "NONE",
        "availability_status": "OFFLINE",
        "pending_earnings_cents": 0,
        "lifetime_paid_cents": 0,
        "rating_avg": 0.0,
        "rating_count": 0,
    })
    store.caregivers[rec["id"]] = rec
    return ok(caregiver_out(rec), status=201)


@bp.route("/marketplace/caregivers/<cid>", methods=["GET"])
def get_one_caregiver(cid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    c = get_caregiver(cid)
    if auth.is_caregiver and auth.user_id != c["id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own record")
    return ok(caregiver_out(c), status=200)


@bp.route("/marketplace/caregivers", methods=["GET"])
def list_caregivers():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    limit, offset = parse_pagination()
    availability = request.args.get("availability_status")
    tier = request.args.get("background_check_tier")

    items = list(store.caregivers.values())
    if availability is not None:
        items = [c for c in items if c["availability_status"] == availability]
    if tier is not None:
        items = [c for c in items if c["background_check_tier"] == tier]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([caregiver_out(c) for c in page], status=200, pagination=meta)


@bp.route("/marketplace/caregivers/<cid>/availability", methods=["POST"])
def set_availability(cid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    c = get_caregiver(cid)
    if auth.is_caregiver and auth.user_id != c["id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only set its own availability")
    body = get_json()
    new_status = v.req_enum(body, "availability_status", AVAILABILITY)

    # A caregiver who is currently SUSPENDED may not move out of suspension;
    # only the platform governs suspension (PRD §3.1).
    if c["availability_status"] == "SUSPENDED" and not auth.is_admin:
        raise err(errors.ERR_FORBIDDEN, "Suspended caregiver cannot change availability")

    c["availability_status"] = new_status
    touch(c)
    return ok(caregiver_out(c), status=200)
