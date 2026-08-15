"""Demand partner endpoints (PRD §3.1): registration, capacity retune (OCC),
and the ACTIVE / THROTTLED / SUSPENDED standing lifecycle."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_state, stale_version, ApiError,
    ERR_DUPLICATE_SEAT, ERR_PARTNER_NOT_RESUMABLE,
)
from middleware import require_roles, ALL_ROLES, ROLE_EXCHANGE_ADMIN
from response import success_object, success_list, paginate
from util import get_body, req_str, opt_str, req_int, opt_int
from services.core import (
    base_record, touch, serialize_partner, recompute_spend_today, _sorted,
)

bp = Blueprint("demand_partners", __name__)


@bp.route("/demand-partners", methods=["POST"])
def create_partner():
    require_roles([ROLE_EXCHANGE_ADMIN])
    body = get_body()
    name = req_str(body, "name")
    seat_id = req_str(body, "seat_id")
    max_qps = req_int(body, "max_qps", min_v=1)
    daily_cap = req_int(body, "daily_cap_micros", min_v=1)
    if any(p["seat_id"] == seat_id for p in store.partners.values()):
        raise ApiError(ERR_DUPLICATE_SEAT, 409, "seat_id is already registered")
    partner = base_record()
    partner.update({
        "name": name,
        "seat_id": seat_id,
        "max_qps": max_qps,
        "daily_cap_micros": daily_cap,
        "status": "ACTIVE",
        "spend_today_micros": 0,
        "current_second_auction_count": 0,
        "lifetime_spend_micros": 0,
        "_throttled_second": None,
    })
    store.partners[partner["id"]] = partner
    return success_object(serialize_partner(partner), 201)


@bp.route("/demand-partners", methods=["GET"])
def list_partners():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    items = list(store.partners.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_partner(p) for p in page], limit, offset, total)


@bp.route("/demand-partners/<demandPartnerId>", methods=["GET"])
def get_partner(demandPartnerId):
    require_roles(ALL_ROLES)
    p = store.partners.get(demandPartnerId)
    if p is None:
        raise not_found("DemandPartner not found")
    return success_object(serialize_partner(p))


@bp.route("/demand-partners/<demandPartnerId>", methods=["PUT"])
def update_partner(demandPartnerId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    body = get_body()
    expected_version = req_int(body, "expected_demand_partner_version")
    name = opt_str(body, "name")
    max_qps = opt_int(body, "max_qps", min_v=1)
    daily_cap = opt_int(body, "daily_cap_micros", min_v=1)
    p = store.partners.get(demandPartnerId)
    if p is None:
        raise not_found("DemandPartner not found")
    if expected_version != p["version"]:
        raise stale_version(
            "expected_demand_partner_version does not match the partner version")
    if name is not None:
        p["name"] = name
    if max_qps is not None:
        p["max_qps"] = max_qps
    if daily_cap is not None:
        p["daily_cap_micros"] = daily_cap
    touch(p)
    return success_object(serialize_partner(p))


@bp.route("/demand-partners/<demandPartnerId>/suspend", methods=["POST"])
def suspend_partner(demandPartnerId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    p = store.partners.get(demandPartnerId)
    if p is None:
        raise not_found("DemandPartner not found")
    if p["status"] not in ("ACTIVE", "THROTTLED"):
        raise invalid_state("DemandPartner is not ACTIVE or THROTTLED")
    p["status"] = "SUSPENDED"
    p["_throttled_second"] = None
    touch(p)
    return success_object(serialize_partner(p))


@bp.route("/demand-partners/<demandPartnerId>/reactivate", methods=["POST"])
def reactivate_partner(demandPartnerId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    p = store.partners.get(demandPartnerId)
    if p is None:
        raise not_found("DemandPartner not found")
    if p["status"] == "ACTIVE":
        raise ApiError(ERR_PARTNER_NOT_RESUMABLE, 409,
                       "DemandPartner is already ACTIVE")
    if p["status"] == "THROTTLED":
        # coming back from THROTTLED resets the per-second counter
        p["status"] = "ACTIVE"
        p["_throttled_second"] = None
        p["current_second_auction_count"] = 0
        touch(p)
    else:  # SUSPENDED -> ACTIVE recomputes spend_today for the current date
        p["status"] = "ACTIVE"
        touch(p)
        recompute_spend_today(p)
    return success_object(serialize_partner(p))
