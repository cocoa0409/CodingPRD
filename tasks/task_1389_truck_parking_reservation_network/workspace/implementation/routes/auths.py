"""Driver authorizations (PRD §3.9)."""
from flask import Blueprint, request

import auth
import domain
import errors
import services
import util

bp = Blueprint("auths", __name__)
LIST_ROLES = ("Driver", "FleetManager", "NetworkAdmin")
AUTH_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED", "REJECTED")


def _scoped(ident, items):
    if ident.role == "Driver":
        return [a for a in items if a["driver_id"] == ident.user_id]
    if ident.role == "FleetManager":
        return [a for a in items if a["fleet_account_id"] == ident.user_id]
    return items


def _visible_auth_or_404(ident, auth_id):
    a = domain.get("driver_authorizations", auth_id)
    if a is None:
        raise errors.not_found("DriverAuthorization not found")
    if ident.role == "Driver" and a["driver_id"] != ident.user_id:
        raise errors.forbidden()
    if ident.role == "FleetManager" and a["fleet_account_id"] != ident.user_id:
        raise errors.forbidden()
    return a


@bp.post("/driver-authorizations")
def create_authorization():
    ident = auth.identity()
    auth.require_roles(ident, ("Driver",))
    body = util.get_body(required=True)
    util.req_fields(body, ["driver_id", "fleet_account_id"])
    driver_id = util.req_str(body, "driver_id")
    fleet_id = util.req_str(body, "fleet_account_id")
    cap = util.opt_int(body, "spend_cap_per_night_cents", None)
    if driver_id != ident.user_id:
        raise errors.forbidden("driver_id must equal X-User-ID")
    if domain.get("drivers", driver_id) is None:
        raise errors.not_found("Driver not found")
    if domain.get("fleet_accounts", fleet_id) is None:
        raise errors.not_found("FleetAccount not found")
    a = domain.new_entity("driver_authorizations", {
        "driver_id": driver_id,
        "fleet_account_id": fleet_id,
        "spend_cap_per_night_cents": cap,
        "status": "PENDING",
        "auto_suspended": False,
    })
    return util.ok(domain.serialize_authorization(a), status=201)


@bp.get("/driver-authorizations")
def list_authorizations():
    ident = auth.identity()
    auth.require_roles(ident, LIST_ROLES)
    driver_f = request.args.get("driver_id")
    fleet_f = request.args.get("fleet_account_id")
    status_f = request.args.get("status")
    items = list(domain.all_of("driver_authorizations"))
    items = _scoped(ident, items)
    if driver_f is not None:
        items = [a for a in items if a["driver_id"] == driver_f]
    if fleet_f is not None:
        items = [a for a in items if a["fleet_account_id"] == fleet_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_authorization(a) for a in page], pagination=pg)


@bp.get("/driver-authorizations/<auth_id>")
def get_authorization(auth_id):
    ident = auth.identity()
    auth.require_roles(ident, LIST_ROLES)
    a = _visible_auth_or_404(ident, auth_id)
    return util.ok(domain.serialize_authorization(a))


@bp.post("/driver-authorizations/<auth_id>/transition")
def transition_authorization(auth_id):
    ident = auth.identity()
    auth.require_roles(ident, ("FleetManager",))
    a = domain.get("driver_authorizations", auth_id)
    if a is None:
        raise errors.not_found("DriverAuthorization not found")
    if a["fleet_account_id"] != ident.user_id:
        raise errors.forbidden("FleetManager may act only on own-fleet authorizations")
    body = util.get_body(required=True)
    util.req_fields(body, ["to"])
    to = util.req_enum(body, "to", AUTH_STATUSES)

    current = a["status"]
    allowed = {
        "ACTIVE": current == "PENDING",
        "REJECTED": current == "PENDING",
        "SUSPENDED": current == "ACTIVE",  # manual suspension (auto_suspended false)
        "REVOKED": current in ("PENDING", "ACTIVE", "SUSPENDED"),
        "PENDING": False,
    }
    if not allowed.get(to, False):
        raise errors.invalid_state(f"DriverAuthorization {current} -> {to} not permitted")

    if to == "ACTIVE":
        fleet = domain.get("fleet_accounts", a["fleet_account_id"])
        if fleet is None or fleet["status"] != "ACTIVE":
            raise errors.fleet_suspended("Fleet must be ACTIVE to approve")
        a["status"] = "ACTIVE"
    elif to == "SUSPENDED":
        a["status"] = "SUSPENDED"
        a["auto_suspended"] = False  # manual suspensions never auto-restore
    else:
        a["status"] = to
    domain.touch(a)
    return util.ok(domain.serialize_authorization(a))
