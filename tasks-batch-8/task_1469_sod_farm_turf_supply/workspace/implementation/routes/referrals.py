"""Crew referral and scheduling (PRD section 3.8)."""
from flask import Blueprint

import db
import services
from auth import check_ownership, require_roles
from db import common_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_CREW_DATE_CONFLICT,
                    ERR_CREW_ZONE_MISMATCH, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND)
from serialize import pub_referral
from util import as_str, body, ok, ok_list, paged, pagination, parse_date, require, sort_created

bp = Blueprint("referrals", __name__)

_REFERRABLE_STATES = {"CONFIRMED", "OUT_FOR_DELIVERY", "DELIVERED",
                      "INSTALLING", "INSTALLED"}


def _get_order(oid):
    order = db.store.orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, f"order {oid} not found")
    return order


@bp.route("/orders/<oid>/crew-referrals", methods=["POST"])
def create_referral(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    payload = body()
    crew_id = as_str(require(payload, "crew_id"), "crew_id")
    crew = db.store.crews.get(crew_id)
    if crew is None:
        raise err(ERR_NOT_FOUND, f"crew {crew_id} not found")
    # state guards
    if order["status"] in ("CLOSED", "CANCELLED"):
        raise err(ERR_ALREADY_TERMINAL, f"order {oid} is {order['status']}")
    if order["status"] not in _REFERRABLE_STATES:
        raise err(ERR_INVALID_STATE,
                  f"order {oid} is {order['status']}; referrals require CONFIRMED or later")
    # domain constraints
    if not crew["active"]:
        raise err(ERR_INVALID_REQUEST, "inactive crews cannot receive new referrals")
    if order["freight_zone"] not in crew["service_zones"]:
        raise err(ERR_CREW_ZONE_MISMATCH,
                  f"crew does not serve freight zone {order['freight_zone']}")
    # at most one non-terminal referral per order: the new one supersedes it
    existing = services.live_referral(oid)
    if existing is not None:
        existing["status"] = "REPLACED"
        db.bump(existing)
    referral = common_fields()
    referral.update({
        "order_id": oid,
        "crew_id": crew_id,
        "status": "REFERRED",
        "scheduled_date": None,
    })
    db.store.crew_referrals[referral["id"]] = referral
    order["crew_referral_status"] = "CREW_REFERRED"
    db.bump(order)
    return ok(pub_referral(referral), 201)


@bp.route("/orders/<oid>/crew-referrals", methods=["GET"])
def list_referrals(oid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    limit, offset = pagination()
    items = sort_created(r for r in db.store.crew_referrals.values()
                         if r["order_id"] == oid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_referral(r) for r in page], total, limit, offset)


@bp.route("/orders/<oid>/crew-schedule", methods=["POST"])
def schedule_crew(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    payload = body()
    scheduled_date = parse_date(require(payload, "scheduled_date"), "scheduled_date")
    if order["status"] in ("CLOSED", "CANCELLED"):
        raise err(ERR_ALREADY_TERMINAL, f"order {oid} is {order['status']}")
    referral = services.live_referral(oid)
    if referral is None or referral["status"] != "REFERRED":
        raise err(ERR_INVALID_STATE, "order has no live REFERRED crew referral")
    if scheduled_date < order["delivery_date"]:
        raise err(ERR_INVALID_REQUEST,
                  "scheduled_date must not be earlier than the order's delivery_date")
    for other in db.store.crew_referrals.values():
        if (other["crew_id"] == referral["crew_id"] and other["id"] != referral["id"]
                and other["status"] == "SCHEDULED"
                and other["scheduled_date"] == scheduled_date):
            raise err(ERR_CREW_DATE_CONFLICT,
                      "crew is already scheduled on that date")
    referral["status"] = "SCHEDULED"
    referral["scheduled_date"] = scheduled_date
    db.bump(referral)
    order["crew_referral_status"] = "CREW_SCHEDULED"
    db.bump(order)
    return ok(pub_referral(referral), 200)
