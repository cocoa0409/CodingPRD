"""Membership packages (PRD §3.10)."""
from fractions import Fraction

from flask import Blueprint, request

import clock
import db
import helpers as h
import response
import util
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_UNAUTHORIZED,
    ERR_RENEWAL_TOO_EARLY,
)
from middleware import authenticate, require_role
from services import packages as pkgsvc

bp = Blueprint("packages", __name__)


@bp.post("/practice/packages")
def enroll():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    body = h.get_body()

    client_id = h.as_str(h.require(body, "client_id"), "client_id")
    client = h.resolve(db.clients, client_id)
    plan_id = h.as_str(h.require(body, "plan_id"), "plan_id")
    plan = h.resolve(db.membership_plans, plan_id)
    cycle_anchor_day = h.opt(body, "cycle_anchor_day", 1)
    cycle_anchor_day = h.as_int(cycle_anchor_day, "cycle_anchor_day", minimum=1, maximum=28)

    cycle_end = pkgsvc.add_one_cycle(clock.now(), cycle_anchor_day)

    ent = h.new_entity({
        "client_id": client_id,
        "plan_id": plan_id,
        "credit_balance_sessions": 0,
        "cycle_anchor_day": cycle_anchor_day,
        "current_cycle_end": util.iso_format(cycle_end),
        "package_status": "ACTIVE",
    })
    db.packages[ent["id"]] = ent
    # Grant included_sessions as opening balance (GRANT ledger entry).
    pkgsvc.write_ledger(ent, "GRANT", plan["included_sessions"])
    return response.success(h.public(ent), status=201)


@bp.get("/practice/packages")
def list_packages():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    limit, offset = h.get_pagination()
    client_id = request.args.get("client_id")
    plan_id = request.args.get("plan_id")
    items = list(db.packages.values())
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if plan_id is not None:
        items = [p for p in items if p["plan_id"] == plan_id]
    if caller.role == "Client":
        items = [p for p in items if p["client_id"] == caller.user_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(p) for p in page], limit, offset, total)


@bp.get("/practice/packages/<id>")
def get_package(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.packages, id)
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    return response.success(h.public(ent))


@bp.get("/practice/packages/<id>/ledger")
def list_ledger(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.packages, id)
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    limit, offset = h.get_pagination()
    items = [e for e in db.ledger_entries.values() if e["package_id"] == id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(e) for e in page], limit, offset, total)


@bp.post("/practice/packages/<id>/renew")
def renew(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.packages, id)
    plan = db.membership_plans[ent["plan_id"]]
    # permitted only while ACTIVE
    if ent["package_status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, message="package not ACTIVE")
    # only when clock has reached or passed current_cycle_end
    cycle_end = util.parse_iso(ent["current_cycle_end"])
    if clock.now() < cycle_end:
        raise ApiError(*ERR_RENEWAL_TOO_EARLY, message="renewal too early")

    # Apply rollover cap BEFORE granting (pinned order).
    current = ent["credit_balance_sessions"]
    cap = plan["rollover_cap_sessions"]
    kept = min(current, cap)
    forfeited = current - kept
    if forfeited > 0:
        pkgsvc.write_ledger(ent, "ROLLOVER_FORFEIT", -forfeited)
    pkgsvc.write_ledger(ent, "GRANT", plan["included_sessions"])
    # advance cycle end by one cycle
    ent["current_cycle_end"] = util.iso_format(
        pkgsvc.add_one_cycle(cycle_end, ent["cycle_anchor_day"]))
    h.touch(ent)
    return response.success(h.public(ent))


@bp.post("/practice/packages/<id>/suspend")
def suspend(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.packages, id)
    if ent["package_status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, message="package not ACTIVE")
    ent["package_status"] = "SUSPENDED"
    h.touch(ent)
    return response.success(h.public(ent))


@bp.post("/practice/packages/<id>/resume")
def resume(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.packages, id)
    if ent["package_status"] != "SUSPENDED":
        raise ApiError(*ERR_INVALID_STATE, message="package not SUSPENDED")
    ent["package_status"] = "ACTIVE"
    h.touch(ent)
    return response.success(h.public(ent))


@bp.post("/practice/packages/<id>/cancel-membership")
def cancel_membership(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.packages, id)
    if ent["package_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(*ERR_INVALID_STATE, message="package not cancellable")
    plan = db.membership_plans[ent["plan_id"]]
    client = db.clients[ent["client_id"]]

    remaining = ent["credit_balance_sessions"]
    if remaining > 0:
        # EXPIRE entry zeroes the balance.
        pkgsvc.write_ledger(ent, "EXPIRE", -remaining)
        # wallet credit += remaining * monthly_fee_cents / included_sessions, round half up
        value = Fraction(remaining * plan["monthly_fee_cents"], plan["included_sessions"])
        client["wallet_credit_cents"] += util.round_half_up(value)
        h.touch(client)
    ent["package_status"] = "CANCELLED"
    h.touch(ent)
    return response.success(h.public(ent))
