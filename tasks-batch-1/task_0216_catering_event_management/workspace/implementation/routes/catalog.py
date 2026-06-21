"""Catalog + operator-surface routes: clients, packages, venues, routes,
clock, staff-pool (PRD §3.1, §3.2, §3.12).
"""
from flask import Blueprint

from common import (
    get_json, stamp_create, touch, paginate, parse_dt,
    require_str, require_int, opt_int, opt_bool, opt_enum, require, require_enum,
)
from db import db
from errors import (
    err, ERR_DUPLICATE_EMAIL, ERR_INVALID_REQUEST,
    ERR_NOT_FOUND, ERR_INVALID_STATE,
)
from middleware import authenticate, authorize
from response import success, success_list
from serializers import (
    ser_client, ser_package, ser_venue, ser_route,
)
from services.helpers import get_or_404
from services import calculations

bp = Blueprint("catalog", __name__)


# ===========================================================================
# Clients (PRD §3.2)
# ===========================================================================
@bp.route("/catering/clients", methods=["POST"])
def create_client():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    company_name = require_str(body, "company_name")
    billing_email = require_str(body, "billing_email")
    tax_exempt = opt_bool(body, "tax_exempt", False)
    gratuity_policy = opt_enum(body, "gratuity_policy", {"INCLUDED", "OPTIONAL"}, "INCLUDED")

    # billing_email unique among ACTIVE clients (PRD §3.2, ERR_DUPLICATE_EMAIL)
    for c in db.clients.values():
        if c["status"] == "ACTIVE" and c["billing_email"] == billing_email:
            raise err(ERR_DUPLICATE_EMAIL, "billing_email already in use by an active client")

    rec = {
        "company_name": company_name,
        "billing_email": billing_email,
        "tax_exempt": tax_exempt,
        "gratuity_policy": gratuity_policy,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.clients[rec["id"]] = rec
    return success(ser_client(rec), status=201)


@bp.route("/catering/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    rec = get_or_404(db.clients, cid)
    return success(ser_client(rec))


@bp.route("/catering/clients", methods=["GET"])
def list_clients():
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "SalesCoordinator"})
    from flask import request
    status = request.args.get("status")
    rows = list(db.clients.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_client(r) for r in page], limit, offset, total)


# ===========================================================================
# Packages (PRD §3.1)
# ===========================================================================
@bp.route("/catering/packages", methods=["POST"])
def create_package():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    name = require_str(body, "name")
    per_head_cents = require_int(body, "per_head_cents", minimum=0)
    min_headcount = require_int(body, "min_headcount", minimum=1)
    lead_time_hours = require_int(body, "lead_time_hours", minimum=0)
    volume_tiers = body.get("volume_tiers") or []
    allergen_flags = body.get("allergen_flags") or []

    volume_tiers = _validate_tiers(volume_tiers, per_head_cents)
    if not isinstance(allergen_flags, list):
        raise err(ERR_INVALID_REQUEST, "allergen_flags must be an array")

    rec = {
        "name": name,
        "per_head_cents": per_head_cents,
        "min_headcount": min_headcount,
        "lead_time_hours": lead_time_hours,
        "volume_tiers": volume_tiers,
        "allergen_flags": allergen_flags,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.packages[rec["id"]] = rec
    return success(ser_package(rec), status=201)


def _validate_tiers(tiers, base):
    if not isinstance(tiers, list):
        raise err(ERR_INVALID_REQUEST, "volume_tiers must be an array")
    prev_min = None
    out = []
    for t in tiers:
        if not isinstance(t, dict) or "min_headcount" not in t or "per_head_cents" not in t:
            raise err(ERR_INVALID_REQUEST, "each volume_tier needs min_headcount and per_head_cents")
        mh = t["min_headcount"]
        phc = t["per_head_cents"]
        if isinstance(mh, bool) or not isinstance(mh, int) or isinstance(phc, bool) or not isinstance(phc, int):
            raise err(ERR_INVALID_REQUEST, "volume_tier fields must be integers")
        if phc > base:
            raise err(ERR_INVALID_REQUEST, "volume_tier per_head_cents must be <= base per_head_cents")
        if prev_min is not None and mh <= prev_min:
            raise err(ERR_INVALID_REQUEST, "volume_tier min_headcount must be strictly increasing")
        prev_min = mh
        out.append({"min_headcount": mh, "per_head_cents": phc})
    return out


@bp.route("/catering/packages/<pid>", methods=["GET"])
def get_package(pid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    rec = get_or_404(db.packages, pid)
    return success(ser_package(rec))


@bp.route("/catering/packages", methods=["GET"])
def list_packages():
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    from flask import request
    status = request.args.get("status")
    rows = list(db.packages.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_package(r) for r in page], limit, offset, total)


@bp.route("/catering/packages/<pid>/retire", methods=["POST"])
def retire_package(pid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    rec = get_or_404(db.packages, pid)
    body = get_json()
    # OCC against package.version (PRD §2.11)
    if "expected_package_version" not in body or body["expected_package_version"] is None:
        raise err(ERR_INVALID_REQUEST, "expected_package_version is required")
    expected = body["expected_package_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_package_version must be an integer")
    if expected != rec["version"]:
        from errors import ERR_STALE_ORDER_VERSION
        raise err(ERR_STALE_ORDER_VERSION, "expected_package_version mismatch")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "package is not ACTIVE")
    rec["status"] = "RETIRED"
    touch(rec)
    return success(ser_package(rec))


# ===========================================================================
# Venues (PRD §3.1)
# ===========================================================================
@bp.route("/catering/venues", methods=["POST"])
def create_venue():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    name = require_str(body, "name")
    tax_rate_bps = require_int(body, "tax_rate_bps", minimum=0)
    if tax_rate_bps > 2000:
        raise err(ERR_INVALID_REQUEST, "tax_rate_bps must be <= 2000")
    service_fee_bps = require_int(body, "service_fee_bps", minimum=0)
    if service_fee_bps > 5000:
        raise err(ERR_INVALID_REQUEST, "service_fee_bps must be <= 5000")
    max_overlapping_events = require_int(body, "max_overlapping_events", minimum=1)

    rec = {
        "name": name,
        "tax_rate_bps": tax_rate_bps,
        "service_fee_bps": service_fee_bps,
        "max_overlapping_events": max_overlapping_events,
    }
    stamp_create(rec)
    db.venues[rec["id"]] = rec
    return success(ser_venue(rec), status=201)


@bp.route("/catering/venues/<vid>", methods=["GET"])
def get_venue(vid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    rec = get_or_404(db.venues, vid)
    return success(ser_venue(rec))


# ===========================================================================
# Service routes (PRD §3.1, §3.11)
# ===========================================================================
@bp.route("/catering/routes", methods=["POST"])
def create_route():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    route_date = parse_dt(require(body, "route_date"))
    vehicle_capacity_legs = require_int(body, "vehicle_capacity_legs", minimum=1)

    rec = {
        "route_date": route_date,
        "vehicle_capacity_legs": vehicle_capacity_legs,
        "posture": "OPEN",
        "dispatched_leg_count": 0,
    }
    stamp_create(rec)
    db.routes[rec["id"]] = rec
    return success(ser_route(rec), status=201)


@bp.route("/catering/routes/<rid>", methods=["GET"])
def get_route(rid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "EventCaptain", "SalesCoordinator"})
    rec = get_or_404(db.routes, rid)
    return success(ser_route(rec))


@bp.route("/catering/routes/<rid>/delivery-legs", methods=["GET"])
def list_route_legs(rid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "EventCaptain", "SalesCoordinator"})
    get_or_404(db.routes, rid)
    from serializers import ser_leg
    rows = [l for l in db.delivery_legs.values() if l["route_id"] == rid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_leg(r) for r in page], limit, offset, total)


# ===========================================================================
# Test-driving clock + staffing pool (PRD §3.12)
# ===========================================================================
@bp.route("/catering/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    db.current_utc = parse_dt(require(body, "to_iso8601"))
    return success({})


@bp.route("/catering/_staff-pool/set_capacity", methods=["POST"])
def set_staff_pool():
    _, role = authenticate()
    authorize(role, {"CateringAdmin"})
    body = get_json()
    db.staff_pool_total = require_int(body, "total_staff", minimum=0)
    return success({})
