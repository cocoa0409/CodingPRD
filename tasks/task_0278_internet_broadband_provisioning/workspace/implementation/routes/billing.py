"""BillingCycle and UsageRecord endpoints (PRD §3.5, §3.10)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_positive_int, require_iso, paginate,
                              sorted_by_created)
from services.serialize import public, public_list
from services import calculations as calc
from services import domain
from timeutil import parse_iso, format_iso

bp = Blueprint("billing", __name__)


# --- BillingCycle ---

@bp.route("/billing-cycles", methods=["POST"])
def create_billing_cycle():
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["account_id", "cycle_start_iso", "cycle_end_iso"])
    account = lookup(db.accounts, body["account_id"])
    start = require_iso(body, "cycle_start_iso")
    end = require_iso(body, "cycle_end_iso")
    if not (end > start):
        err("ERR_INVALID_REQUEST", "cycle_end_iso must be after cycle_start_iso.")
    rec = db.make_record({
        "account_id": account["id"],
        "cycle_start_iso": body["cycle_start_iso"],
        "cycle_end_iso": body["cycle_end_iso"],
        "usage_gb": 0,
        "billing_state": "OPEN",
        "throttle_state": "UNCAPPED",
        "overage_charge_cents": 0,
        "total_due_cents": 0,
    }, versioned=db.VERSIONED)
    db.billing_cycles[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/billing-cycles/<rid>", methods=["GET"])
def get_billing_cycle(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.billing_cycles, rid)
    return object_response(public(rec), 200)


@bp.route("/billing-cycles", methods=["GET"])
def list_billing_cycles():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.billing_cycles.values())
    for f in ("account_id", "billing_state"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/billing-cycles/<rid>/overage-estimate", methods=["GET"])
def overage_estimate(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    cycle = lookup(db.billing_cycles, rid)
    account = db.accounts.get(cycle["account_id"])
    plan = db.service_plans.get(account["plan_id"]) if account else None

    start = parse_iso(cycle["cycle_start_iso"])
    end = parse_iso(cycle["cycle_end_iso"])
    cycle_days = calc.whole_days_in_window(start, end)

    as_of_raw = request.args.get("as_of_iso")
    if as_of_raw is not None:
        as_of = parse_iso(as_of_raw)
        if as_of is None:
            err("ERR_INVALID_REQUEST", "as_of_iso must be an ISO 8601 timestamp.")
    else:
        from clock import get_clock
        as_of = get_clock().now()

    # usage so far = sum of records posted within window up to as_of.
    usage_so_far = 0
    for u in db.usage_records.values():
        if u["billing_cycle_id"] != cycle["id"]:
            continue
        posted = parse_iso(u["posted_at_iso"])
        if posted is None:
            continue
        if start <= posted < end and posted <= as_of:
            usage_so_far += u["gb"]

    days_elapsed = calc.whole_days_used(start, as_of)
    estimate = 0
    if plan is not None:
        estimate = calc.overage_estimate_cents(
            usage_so_far, days_elapsed, cycle_days, plan)

    out = public(cycle)
    out["overage_charge_cents"] = estimate
    return object_response(out, 200)


@bp.route("/billing-cycles/<rid>/close", methods=["POST"])
def close_cycle(rid):
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    get_json_body()
    cycle = lookup(db.billing_cycles, rid)
    if cycle["billing_state"] != "OPEN":
        err("ERR_INVALID_STATE", "Cycle must be OPEN to close.")
    # No OutageEvent for this cycle may still be OPEN.
    for o in db.outage_events.values():
        if o["billing_cycle_id"] == cycle["id"] and o["status"] == "OPEN":
            err("ERR_CYCLE_HAS_OPEN_OUTAGE",
                "Cycle has an OPEN outage event.")
    domain.close_cycle(cycle)
    return object_response(public(cycle), 200)


@bp.route("/billing-cycles/<rid>/finalize", methods=["POST"])
def finalize_cycle(rid):
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    get_json_body()
    cycle = lookup(db.billing_cycles, rid)
    if cycle["billing_state"] != "CLOSED":
        err("ERR_CYCLE_NOT_CLOSED", "Cycle must be CLOSED to finalize.")
    domain.finalize_cycle(cycle)
    return object_response(public(cycle), 200)


# --- UsageRecord ---

@bp.route("/usage-records", methods=["POST"])
def post_usage_record():
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps"})
    body = get_json_body()
    require_fields(body, ["account_id", "billing_cycle_id", "posted_at_iso", "gb"])
    account = lookup(db.accounts, body["account_id"])
    cycle = lookup(db.billing_cycles, body["billing_cycle_id"])
    posted = require_iso(body, "posted_at_iso")
    gb = require_positive_int(body, "gb")

    # posted_at_iso must fall within the cycle window (422).
    start = parse_iso(cycle["cycle_start_iso"])
    end = parse_iso(cycle["cycle_end_iso"])
    if not (start <= posted < end):
        err("ERR_USAGE_OUTSIDE_CYCLE",
            "posted_at_iso falls outside the cycle window.")

    rec = db.make_record({
        "account_id": account["id"],
        "billing_cycle_id": cycle["id"],
        "posted_at_iso": body["posted_at_iso"],
        "gb": gb,
    }, versioned=db.LEAN)
    db.usage_records[rec["id"]] = rec

    # Side effect: cycle.usage_gb += gb.
    cycle["usage_gb"] = cycle.get("usage_gb", 0) + gb
    touch(cycle)

    # Throttle trigger (PRD §3.5): only while cycle OPEN, policy THROTTLE,
    # cumulative usage strictly > included_gb.
    plan = db.service_plans.get(account["plan_id"])
    if (plan is not None and plan["overage_policy"] == "THROTTLE"
            and cycle["billing_state"] == "OPEN"
            and cycle["usage_gb"] > plan["included_gb"]
            and cycle["throttle_state"] == "UNCAPPED"):
        cycle["throttle_state"] = "THROTTLED"
        touch(cycle)
        if account["status"] == "ACTIVE" and account["service_state"] == "ONLINE":
            account["service_state"] = "THROTTLED"
            touch(account)

    return object_response(public(rec), 201)


@bp.route("/usage-records/<rid>", methods=["GET"])
def get_usage_record(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.usage_records, rid)
    return object_response(public(rec), 200)


@bp.route("/usage-records", methods=["GET"])
def list_usage_records():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.usage_records.values())
    for f in ("account_id", "billing_cycle_id"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)
