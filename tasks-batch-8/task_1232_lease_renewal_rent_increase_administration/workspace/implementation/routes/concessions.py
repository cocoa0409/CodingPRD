from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_OFFER_NOT_FOUND, ERR_CONCESSION_NOT_FOUND,
    ERR_OFFER_NOT_COUNTERED, ERR_SEGREGATION_OF_DUTIES, ERR_CONCESSION_TIER_EXCEEDED,
    ERR_CONCESSION_NOT_SUBMITTED, ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX,
)
from middleware import require_roles
from response import success_object, success_list
from services.calc import (
    concession_bps_for, AGENT_MAX_CONCESSION_BPS, MANAGER_MAX_CONCESSION_BPS,
    ABSOLUTE_MAX_CONCESSION_BPS,
)
from services.common import new_entity, touch

bp = Blueprint("concessions", __name__)


def _serialize(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "offer_id": c["offer_id"],
        "requested_rent_cents": c["requested_rent_cents"],
        "reason": c.get("reason"),
        "concession_bps": c["concession_bps"],
        "requested_by_user_id": c["requested_by_user_id"],
        "decided_by_user_id": c.get("decided_by_user_id"),
        "status": c["status"],
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@bp.route("/renewal-offers/<offer_id>/concession-approvals", methods=["POST"])
def create_concession(offer_id):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    body = request.get_json(silent=True) or {}
    requested_rent = body.get("requested_rent_cents")
    reason = body.get("reason")
    if not isinstance(requested_rent, int) or isinstance(requested_rent, bool) or requested_rent <= 0:
        raise_err(ERR_INVALID_REQUEST, "requested_rent_cents must be > 0")
    if reason is not None and not isinstance(reason, str):
        raise_err(ERR_INVALID_REQUEST, "reason must be string")

    o = store.renewal_offers.get(offer_id)
    if o is None:
        raise_err(ERR_OFFER_NOT_FOUND, "offer not found")

    if o["status"] != "COUNTERED":
        raise_err(ERR_OFFER_NOT_COUNTERED, "offer not COUNTERED")

    # Compute concession_bps and check absolute max
    cbps = concession_bps_for(o["proposed_rent_cents"], requested_rent)
    if cbps > ABSOLUTE_MAX_CONCESSION_BPS:
        raise_err(ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX, "concession exceeds absolute max")

    rec = new_entity()
    rec.update({
        "offer_id": offer_id,
        "requested_rent_cents": requested_rent,
        "reason": reason,
        "concession_bps": cbps,
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "status": "SUBMITTED",
    })
    store.concession_approvals[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/concession-approvals", methods=["GET"])
def list_concessions():
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    limit, offset = _get_pagination()
    offer_id = request.args.get("offer_id")
    status = request.args.get("status")
    items = list(store.concession_approvals.values())
    if offer_id:
        items = [c for c in items if c["offer_id"] == offer_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(c) for c in page], limit, offset, total)


@bp.route("/concession-approvals/<cid>", methods=["GET"])
def get_concession(cid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    c = store.concession_approvals.get(cid)
    if c is None:
        raise_err(ERR_CONCESSION_NOT_FOUND, "concession not found")
    return success_object(_serialize(c))


@bp.route("/concession-approvals/<cid>/approve", methods=["POST"])
def approve_concession(cid):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    c = store.concession_approvals.get(cid)
    if c is None:
        raise_err(ERR_CONCESSION_NOT_FOUND, "concession not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_CONCESSION_NOT_SUBMITTED, "concession not SUBMITTED")
    # Linked offer must be COUNTERED
    o = store.renewal_offers.get(c["offer_id"])
    if o is None or o["status"] != "COUNTERED":
        raise_err(ERR_OFFER_NOT_COUNTERED, "offer not COUNTERED")
    # SoD
    if user_id == c["requested_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "approver must differ from requester")
    # Tier
    tier_cap = {
        "LeasingAgent": AGENT_MAX_CONCESSION_BPS,
        "PropertyManager": MANAGER_MAX_CONCESSION_BPS,
        "RegionalDirector": ABSOLUTE_MAX_CONCESSION_BPS,
    }[role]
    if c["concession_bps"] > tier_cap:
        raise_err(ERR_CONCESSION_TIER_EXCEEDED, "concession exceeds approver tier")
    c["status"] = "APPROVED"
    c["decided_by_user_id"] = user_id
    touch(c)
    return success_object(_serialize(c))


@bp.route("/concession-approvals/<cid>/deny", methods=["POST"])
def deny_concession(cid):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    c = store.concession_approvals.get(cid)
    if c is None:
        raise_err(ERR_CONCESSION_NOT_FOUND, "concession not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_CONCESSION_NOT_SUBMITTED, "concession not SUBMITTED")
    if user_id == c["requested_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "denier must differ from requester")
    c["status"] = "DENIED"
    c["decided_by_user_id"] = user_id
    touch(c)
    return success_object(_serialize(c))
