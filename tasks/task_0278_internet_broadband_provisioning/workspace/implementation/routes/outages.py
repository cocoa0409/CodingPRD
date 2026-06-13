"""OutageEvent and AccountCredit endpoints (PRD §3.6, §3.11)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_iso, paginate, sorted_by_created)
from services.serialize import public, public_list
from services import calculations as calc
from services import domain
from timeutil import parse_iso

bp = Blueprint("outages", __name__)


@bp.route("/outage-events", methods=["POST"])
def create_outage_event():
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    body = get_json_body()
    require_fields(body, ["account_id", "billing_cycle_id", "started_at_iso"])
    account = lookup(db.accounts, body["account_id"])
    cycle = lookup(db.billing_cycles, body["billing_cycle_id"])
    started = require_iso(body, "started_at_iso")

    start = parse_iso(cycle["cycle_start_iso"])
    end = parse_iso(cycle["cycle_end_iso"])
    if not (start <= started < end):
        err("ERR_OUTAGE_OUTSIDE_CYCLE",
            "started_at_iso falls outside the cycle window.")

    rec = db.make_record({
        "account_id": account["id"],
        "billing_cycle_id": cycle["id"],
        "started_at_iso": body["started_at_iso"],
        "ended_at_iso": None,
        "duration_minutes": 0,
        "status": "OPEN",
    }, versioned=db.VERSIONED)
    db.outage_events[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/outage-events/<rid>", methods=["GET"])
def get_outage_event(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.outage_events, rid)
    return object_response(public(rec), 200)


@bp.route("/outage-events", methods=["GET"])
def list_outage_events():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.outage_events.values())
    for f in ("account_id", "billing_cycle_id"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/outage-events/<rid>/resolve", methods=["POST"])
def resolve_outage(rid):
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    rec = lookup(db.outage_events, rid)
    body = get_json_body()
    require_fields(body, ["ended_at_iso"])
    ended = require_iso(body, "ended_at_iso")
    if rec["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Outage must be OPEN to resolve.")
    started = parse_iso(rec["started_at_iso"])
    if not (ended > started):
        err("ERR_INVALID_REQUEST", "ended_at_iso must be strictly after started_at_iso.")
    rec["ended_at_iso"] = body["ended_at_iso"]
    rec["duration_minutes"] = calc.whole_minutes_between(started, ended)
    rec["status"] = "RESOLVED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/outage-events/<rid>/issue-credit", methods=["POST"])
def issue_credit(rid):
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    get_json_body()
    rec = lookup(db.outage_events, rid)
    if rec["status"] != "RESOLVED":
        err("ERR_INVALID_STATE", "Outage must be RESOLVED to credit.")
    if rec["duration_minutes"] < calc.MIN_QUALIFYING_MINUTES:
        err("ERR_OUTAGE_BELOW_SLA",
            "Outage duration is below the SLA qualifying threshold.")

    account = db.accounts.get(rec["account_id"])
    cycle = db.billing_cycles.get(rec["billing_cycle_id"])
    plan = db.service_plans.get(account["plan_id"]) if account else None

    cycle_minutes = calc.whole_minutes_between(
        parse_iso(cycle["cycle_start_iso"]), parse_iso(cycle["cycle_end_iso"]))

    # Qualifying minutes: this account's outages in this cycle whose status is
    # RESOLVED or CREDITED and duration >= 240, intervals merged (§3.6).
    # The outage being credited is currently RESOLVED, so it is included.
    intervals = []
    for o in db.outage_events.values():
        if o["account_id"] != rec["account_id"]:
            continue
        if o["billing_cycle_id"] != rec["billing_cycle_id"]:
            continue
        if o["status"] not in ("RESOLVED", "CREDITED"):
            continue
        if o["duration_minutes"] < calc.MIN_QUALIFYING_MINUTES:
            continue
        s = parse_iso(o["started_at_iso"])
        e = parse_iso(o["ended_at_iso"]) if o["ended_at_iso"] else None
        if s is None or e is None:
            continue
        intervals.append((s, e))
    qualifying_minutes = calc.merge_intervals(intervals)

    amount = calc.outage_credit_cents(
        plan["monthly_fee_cents"], qualifying_minutes, cycle_minutes) if plan else 0

    rec["status"] = "CREDITED"
    touch(rec)
    domain.emit_credit(rec["account_id"], "OUTAGE", rec["id"], amount)
    return object_response(public(rec), 200)


@bp.route("/outage-events/<rid>/dismiss", methods=["POST"])
def dismiss_outage(rid):
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    get_json_body()
    rec = lookup(db.outage_events, rid)
    if rec["status"] != "RESOLVED":
        err("ERR_INVALID_STATE", "Outage must be RESOLVED to dismiss.")
    rec["status"] = "DISMISSED"
    touch(rec)
    return object_response(public(rec), 200)


# --- AccountCredit (read-only) ---

@bp.route("/account-credits/<rid>", methods=["GET"])
def get_account_credit(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.account_credits, rid)
    return object_response(public(rec), 200)


@bp.route("/account-credits", methods=["GET"])
def list_account_credits():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.account_credits.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    applied = request.args.get("applied")
    if applied is not None:
        want = applied.lower() == "true"
        recs = [r for r in recs if bool(r["applied"]) == want]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)
