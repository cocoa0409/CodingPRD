"""SponsorEntitlement routes (§3.8)."""

from flask import Blueprint, g

import response as resp
from middleware import require_roles
from services import entitlement_service
from services.common import serialize


bp = Blueprint("entitlements", __name__)


@bp.route("/exhibitions/<exhibition_id>/entitlements", methods=["POST"])
def create(exhibition_id):
    require_roles("VenueAdmin")
    row = entitlement_service.create_entitlement(exhibition_id, g.body)
    return resp.created(serialize(row))


@bp.route("/entitlements/<eid>/start", methods=["POST"])
def start(eid):
    require_roles("VenueOps")
    row = entitlement_service.start_entitlement(eid, g.body)
    return resp.success(serialize(row))


@bp.route("/entitlements/<eid>/fulfill", methods=["POST"])
def fulfill(eid):
    require_roles("VenueOps")
    row = entitlement_service.fulfill_entitlement(eid, g.body)
    return resp.success(serialize(row))


@bp.route("/entitlements/<eid>/mark-missed", methods=["POST"])
def mark_missed(eid):
    require_roles("VenueAdmin")
    row = entitlement_service.mark_missed(eid, g.body)
    return resp.success(serialize(row))


@bp.route("/entitlements/<eid>/offer-make-good", methods=["POST"])
def offer_make_good(eid):
    require_roles("VenueAdmin")
    row = entitlement_service.offer_make_good(eid, g.body)
    return resp.success(serialize(row))


@bp.route("/entitlements/<eid>/accept-make-good", methods=["POST"])
def accept_make_good(eid):
    require_roles("Exhibitor")
    row = entitlement_service.accept_make_good(eid, g.body)
    return resp.success(serialize(row))


@bp.route("/entitlements/<eid>/waive", methods=["POST"])
def waive(eid):
    require_roles("Exhibitor")
    row = entitlement_service.waive_entitlement(eid, g.body)
    return resp.success(serialize(row))
