from flask import Blueprint, request

import clock
from db import store
from errors import ApiError, ERR_INVALID_STATE
from middleware import (
    authenticate, require_roles, get_body, f_str, f_int, f_num, f_dt,
    invalid, not_found, paginate,
)
from response import success_object, success_list
from services.derived import ALLOWED_INCREMENTS_CENTS
from services.ops import stamp, touch
from services.serialize import portal_json, blackout_json, subscription_json

bp = Blueprint("portals", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")


def _get_portal(portal_id):
    portal = store.portals.get(portal_id)
    if portal is None:
        raise not_found("PortalAccount not found")
    return portal


@bp.route("/portal-accounts", methods=["POST"])
def create_portal():
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    body = get_body()
    portal_name = f_str(body, "portal_name", required=True)
    sla_seconds = f_int(body, "sla_seconds")
    discount_pct = f_num(body, "discount_pct")
    increment = f_int(body, "rounding_increment_cents")
    if increment is not None and increment not in ALLOWED_INCREMENTS_CENTS:
        raise invalid(
            "rounding_increment_cents must be one of 10000, 50000, 100000, 1000000")
    now = clock.now()
    portal = stamp({
        "portal_name": portal_name,
        "status": "ACTIVE",
        "sla_seconds": 3600 if sla_seconds is None else sla_seconds,
        "discount_pct": 0 if discount_pct is None else discount_pct,
        "rounding_increment_cents":
            100000 if increment is None else increment,
    }, now)
    store.portals[portal["id"]] = portal
    return success_object(portal_json(portal), status=201)


@bp.route("/portal-accounts", methods=["GET"])
def list_portals():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    status = request.args.get("status")
    items = sorted(store.portals.values(),
                   key=lambda p: (p["created_at"], p["_seq"]))
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([portal_json(p) for p in page], limit, offset, total)


@bp.route("/portal-accounts/<portal_id>", methods=["GET"])
def get_portal(portal_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    return success_object(portal_json(_get_portal(portal_id)))


@bp.route("/portal-accounts/<portal_id>/suspend", methods=["POST"])
def suspend_portal(portal_id):
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    portal = _get_portal(portal_id)
    if portal["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "suspend requires portal status ACTIVE")
    portal["status"] = "SUSPENDED"
    touch(portal, clock.now())
    return success_object(portal_json(portal))


@bp.route("/portal-accounts/<portal_id>/resume", methods=["POST"])
def resume_portal(portal_id):
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    portal = _get_portal(portal_id)
    if portal["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "resume requires portal status SUSPENDED")
    portal["status"] = "ACTIVE"
    touch(portal, clock.now())
    return success_object(portal_json(portal))


@bp.route("/portal-accounts/<portal_id>/blackout-windows", methods=["POST"])
def create_blackout(portal_id):
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    portal = _get_portal(portal_id)
    body = get_body()
    starts_at = f_dt(body, "starts_at", required=True)
    ends_at = f_dt(body, "ends_at", required=True)
    reason = f_str(body, "reason")
    if not ends_at > starts_at:
        raise invalid("ends_at must be strictly later than starts_at")
    blackout = stamp({
        "portal_account_id": portal["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": reason,
    }, clock.now(), light=True)
    store.blackouts[blackout["id"]] = blackout
    return success_object(blackout_json(blackout), status=201)


@bp.route("/portal-accounts/<portal_id>/blackout-windows", methods=["GET"])
def list_blackouts(portal_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    portal = _get_portal(portal_id)
    items = sorted(
        (b for b in store.blackouts.values()
         if b["portal_account_id"] == portal["id"]),
        key=lambda b: (b["created_at"], b["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([blackout_json(b) for b in page], limit, offset, total)


@bp.route("/portal-accounts/<portal_id>/feed-subscriptions", methods=["GET"])
def portal_subscriptions(portal_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    portal = _get_portal(portal_id)
    items = sorted(
        (s for s in store.subscriptions.values()
         if s["portal_account_id"] == portal["id"]),
        key=lambda s: (s["created_at"], s["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([subscription_json(s) for s in page],
                        limit, offset, total)
