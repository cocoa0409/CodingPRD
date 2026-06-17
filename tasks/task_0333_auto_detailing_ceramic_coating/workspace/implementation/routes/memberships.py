"""Membership endpoints and lifecycle (PRD §3.5).

Lifecycle: PENDING_PAYMENT -> ACTIVE -> {renew ACTIVE, PAST_DUE, CANCELLED};
PAST_DUE -> {ACTIVE (cure), LAPSED}. Terminal: CANCELLED, LAPSED.
"""
from flask import Blueprint, request

import auth
import clock
import db
import domain
from domain import touch, recompute_credits_remaining, package_pricing, CYCLE_DAYS
from errors import err
from recordutil import base_versioned, sorted_by_creation
from response import object_response, array_response
from serialize import serialize, serialize_list
from timeutil import add_days
from validation import (
    get_body, require_str, require_enum, require_int,
    parse_pagination, paginate, VEHICLE_SIZES,
)

bp = Blueprint("memberships", __name__)


def _uid():
    return request.headers.get("X-User-ID")


@bp.route("/detailing/memberships", methods=["POST"])
def create_membership():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    default_size = require_enum(body, "default_vehicle_size", VEHICLE_SIZES)
    # FK existence (priority 5) — but ownership (priority 3) is checked first.
    cust = db.customers.get(customer_id)
    if cust is not None:
        auth.require_owner(role, _uid(), customer_id)
    if cust is None:
        raise err("ERR_FK_NOT_FOUND", "customer_id not found")
    rec = base_versioned()
    rec.update({
        "customer_id": customer_id,
        "status": "PENDING_PAYMENT",
        "monthly_fee_cents": 4900,
        "cycle_start_utc": None,
        "cycle_anchor_day": 30,
        "wash_credit_value_cents": None,
        "default_vehicle_size": default_size,
        "credits_granted_total": 0,
        "credits_consumed_total": 0,
        "credits_expired_total": 0,
        "credits_remaining": 0,
    })
    db.memberships[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    rec = db.memberships.get(mid)
    if not rec:
        raise err("ERR_NOT_FOUND", "membership not found")
    auth.require_owner(role, _uid(), rec["customer_id"])
    return object_response(serialize(rec))


def _load(mid, role, allowed, own_ok=True):
    auth.require_role(role, allowed)
    rec = db.memberships.get(mid)
    if not rec:
        raise err("ERR_NOT_FOUND", "membership not found")
    if own_ok:
        auth.require_owner(role, _uid(), rec["customer_id"])
    return rec


@bp.route("/detailing/memberships/<mid>/activate", methods=["POST"])
def activate(mid):
    _, role = auth.get_identity()
    rec = _load(mid, role, {"Customer", "Scheduler", "ShopManager"})
    status = rec["status"]
    if status == "PENDING_PAYMENT":
        rec["status"] = "ACTIVE"
        rec["cycle_start_utc"] = clock.now()
        # freeze wash_credit_value_cents = member-discounted WASH price at default size.
        _, _, pkg_net = package_pricing("WASH", rec["default_vehicle_size"], True)
        rec["wash_credit_value_cents"] = pkg_net
        rec["credits_granted_total"] += 1
        recompute_credits_remaining(rec)
        cust = db.customers.get(rec["customer_id"])
        if cust:
            cust["membership_id"] = rec["id"]
            touch(cust)
        touch(rec)
        return object_response(serialize(rec))
    if status == "PAST_DUE":
        # cure past-due back to ACTIVE: advance cycle, grant a fresh credit.
        rec["status"] = "ACTIVE"
        rec["cycle_start_utc"] = add_days(rec["cycle_start_utc"], CYCLE_DAYS)
        rec["credits_granted_total"] += 1
        recompute_credits_remaining(rec)
        touch(rec)
        return object_response(serialize(rec))
    raise err("ERR_INVALID_STATE", "membership cannot be activated from its current state")


@bp.route("/detailing/memberships/<mid>/renew", methods=["POST"])
def renew(mid):
    _, role = auth.get_identity()
    rec = _load(mid, role, {"Scheduler", "ShopManager"}, own_ok=False)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "renew requires ACTIVE")
    if clock.now() < add_days(rec["cycle_start_utc"], CYCLE_DAYS):
        raise err("ERR_INVALID_STATE", "cycle has not elapsed")
    # expire any unconsumed prior-cycle credit, then grant one new credit.
    rec["credits_expired_total"] += rec["credits_remaining"]
    rec["credits_granted_total"] += 1
    recompute_credits_remaining(rec)
    rec["cycle_start_utc"] = add_days(rec["cycle_start_utc"], CYCLE_DAYS)
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/detailing/memberships/<mid>/mark-past-due", methods=["POST"])
def mark_past_due(mid):
    _, role = auth.get_identity()
    rec = _load(mid, role, {"Scheduler", "ShopManager"}, own_ok=False)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "mark-past-due requires ACTIVE")
    if clock.now() < add_days(rec["cycle_start_utc"], CYCLE_DAYS):
        raise err("ERR_INVALID_STATE", "cycle has not elapsed")
    rec["status"] = "PAST_DUE"
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/detailing/memberships/<mid>/lapse", methods=["POST"])
def lapse(mid):
    _, role = auth.get_identity()
    rec = _load(mid, role, {"Scheduler", "ShopManager"}, own_ok=False)
    if rec["status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "lapse requires PAST_DUE")
    if clock.now() < add_days(rec["cycle_start_utc"], CYCLE_DAYS):
        raise err("ERR_INVALID_STATE", "grace period not exhausted")
    rec["status"] = "LAPSED"
    rec["credits_expired_total"] += rec["credits_remaining"]
    recompute_credits_remaining(rec)
    cust = db.customers.get(rec["customer_id"])
    if cust and cust.get("membership_id") == rec["id"]:
        cust["membership_id"] = None
        touch(cust)
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/detailing/memberships/<mid>/cancel", methods=["POST"])
def cancel(mid):
    _, role = auth.get_identity()
    rec = _load(mid, role, {"Customer", "ShopManager"})
    body = get_body()
    expected = require_int(body, "expected_membership_version")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "cancel requires ACTIVE")
    if expected != rec["version"]:
        raise err("ERR_STALE_CLAIM_VERSION", "membership version mismatch")
    rec["status"] = "CANCELLED"
    rec["credits_expired_total"] += rec["credits_remaining"]
    recompute_credits_remaining(rec)
    cust = db.customers.get(rec["customer_id"])
    if cust and cust.get("membership_id") == rec["id"]:
        cust["membership_id"] = None
        touch(cust)
    touch(rec)
    return object_response(serialize(rec))
