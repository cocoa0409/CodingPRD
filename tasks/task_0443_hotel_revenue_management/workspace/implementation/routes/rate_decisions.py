"""RateDecision endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_PLAN_CLOSED,
    ERR_RATE_BELOW_FLOOR, ERR_INVALID_STATE, ERR_MISSING_INVENTORY_DAY,
    ERR_STALE_VERSION,
)
from services.common import (
    get_body, require_str, require_number, require_datetime, require_int,
    opt_str, stay_date_midnight, iso_out, stamp_new, bump,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_rate_decision
from services.calc import (
    compute_yield, master_bar_plan, resync_plan_channels, recompute_property_kpi,
    recompute_availability,
)

bp = Blueprint("rate_decisions", __name__)

READ_ROLES = {"RevenueManager", "ChannelManager", "Analyst"}


@bp.route("/rate-decisions", methods=["POST"])
def create_rate_decision():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    rate_plan_id = require_str(body, "rate_plan_id")
    stay_dt = require_datetime(body, "stay_date")
    requested_rate = require_number(body, "requested_rate")
    if requested_rate < 0:
        raise err(ERR_INVALID_REQUEST, "requested_rate must be >= 0")

    plan = db.rate_plans.get(rate_plan_id)
    if plan is None:
        raise err(ERR_FK_NOT_FOUND, "rate_plan_id does not reference an existing rate plan")

    # Plan must be ACTIVE (create against CLOSED plan -> ERR_PLAN_CLOSED).
    if plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_CLOSED, "Rate plan is CLOSED")

    # requested_rate >= plan.floor_rate, before any yield.
    if requested_rate < plan["floor_rate"]:
        raise err(ERR_RATE_BELOW_FLOOR, "requested_rate is below the plan's floor_rate")

    stay_mid = stay_date_midnight(stay_dt)
    rec = {
        "id": new_id(),
        "rate_plan_id": rate_plan_id,
        "stay_date": iso_out(stay_mid),
        "stay_date_key": stay_mid.strftime("%Y-%m-%d"),
        "status": "DRAFT",
        "requested_rate": requested_rate,
        "yielded_rate": None,
        "applied_yield_rule_id": None,
        "last_room_premium_applied": False,
        "reject_reason": None,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.rate_decisions[rec["id"]] = rec
    return success(ser_rate_decision(rec), status=201)


@bp.route("/rate-decisions/<did>", methods=["GET"])
def get_rate_decision(did):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.rate_decisions, did)
    return success(ser_rate_decision(rec), status=200)


@bp.route("/rate-decisions", methods=["GET"])
def list_rate_decisions():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    rate_plan_id = request.args.get("rate_plan_id")
    stay_date = request.args.get("stay_date")
    applied_rule = request.args.get("applied_yield_rule_id")
    stay_key = None
    if stay_date:
        from services.common import parse_iso
        stay_key = stay_date_midnight(parse_iso(stay_date, "stay_date")).strftime("%Y-%m-%d")
    items = []
    for d in db.rate_decisions.values():
        if rate_plan_id is not None and d["rate_plan_id"] != rate_plan_id:
            continue
        if stay_key is not None and d["stay_date_key"] != stay_key:
            continue
        if applied_rule is not None and d["applied_yield_rule_id"] != applied_rule:
            continue
        items.append(d)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_rate_decision(d) for d in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/rate-decisions/<did>/publish", methods=["POST"])
def publish_rate_decision(did):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    decision = get_or_404(db.rate_decisions, did)
    body = get_body()
    # expected_rate_plan_version is required for publish (OCC).
    expected_version = require_int(body, "expected_rate_plan_version")

    plan = db.rate_plans.get(decision["rate_plan_id"])

    # Gating order (PRD §3.4): state legality -> plan ACTIVE -> inventory day
    # exists -> OCC. State legality before concurrency.
    if decision["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Decision is not in DRAFT state")
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_CLOSED, "Rate plan is CLOSED")

    room_type_id = plan["room_type_id"]
    inv = _inv_for(room_type_id, decision["stay_date_key"])
    if inv is None:
        raise err(ERR_MISSING_INVENTORY_DAY, "No InventoryDay exists for the decision's stay date")

    if expected_version != plan["version"]:
        raise err(ERR_STALE_VERSION, "expected_rate_plan_version does not match plan version")

    # Compute yield (pinned order). Pass requested_rate via a calc helper key.
    recompute_availability(inv)
    plan["requested_rate_for_calc"] = decision["requested_rate"]
    yielded, applied_rule_id, premium = compute_yield(plan, inv, _property_id_of(room_type_id))
    plan.pop("requested_rate_for_calc", None)

    decision["yielded_rate"] = yielded
    decision["applied_yield_rule_id"] = applied_rule_id
    decision["last_room_premium_applied"] = premium
    decision["status"] = "PUBLISHED"
    bump(decision)

    # plan.published_rate = yielded_rate; plan.version += 1.
    plan["published_rate"] = yielded
    bump(plan)

    # Hop 1: prior PUBLISHED decision on same (plan, stay_date) -> SUPERSEDED.
    for d in db.rate_decisions.values():
        if d["id"] == decision["id"]:
            continue
        if (d["rate_plan_id"] == decision["rate_plan_id"]
                and d["stay_date_key"] == decision["stay_date_key"]
                and d["status"] == "PUBLISHED"):
            d["status"] = "SUPERSEDED"
            bump(d)

    # Hop 2: master BAR only — re-sync channel mappings under the plan.
    mb = master_bar_plan(room_type_id)
    if mb is not None and mb["id"] == plan["id"]:
        resync_plan_channels(plan["id"], bump)

    # Hop 3: property KPI recompute.
    prop = db.properties.get(_property_id_of(room_type_id))
    if prop is not None:
        recompute_property_kpi(prop)
        bump(prop)

    return success(ser_rate_decision(decision), status=200)


@bp.route("/rate-decisions/<did>/reject", methods=["POST"])
def reject_rate_decision(did):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    decision = get_or_404(db.rate_decisions, did)
    body = get_body()
    if decision["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Decision is not in DRAFT state")
    reason = opt_str(body, "reject_reason", None)
    decision["reject_reason"] = reason
    decision["status"] = "REJECTED"
    # yielded_rate stays null; no published_rate change, no sync, no KPI recompute.
    bump(decision)
    return success(ser_rate_decision(decision), status=200)


def _inv_for(room_type_id, stay_key):
    for inv in db.inventory_days.values():
        if inv["room_type_id"] == room_type_id and inv["stay_date_key"] == stay_key:
            return inv
    return None


def _property_id_of(room_type_id):
    rt = db.room_types.get(room_type_id)
    return rt["property_id"] if rt else None
