"""Reforecast governance: cycles and chase-or-cancel decisions."""
from flask import Blueprint, request

from common import (F, ROLE_PLANNER, ROLE_DIRECTOR, ROLE_BUYER, PLANNING_ROLES,
                    auth, fail, page_of, pagination, parse_input, public,
                    public_list, respond)
import calc
import store
import svc
from store import db, make_row, touch

bp = Blueprint("gov", __name__)


def _filter(rows, name, field=None):
    value = request.args.get(name)
    if value is None:
        return rows
    return [r for r in rows if r.get(field or name) == value]


# ---------------------------------------------------------------------------
# Reforecast cycles
# ---------------------------------------------------------------------------
@bp.post("/otb/category-plans/<rid>/reforecasts")
def open_reforecast(rid):
    auth([ROLE_PLANNER])
    data = parse_input([F("reason_note", "str", min_len=1, max_len=1000),
                        F("expected_category_plan_version", "int", minimum=0)])
    plan = store.get_plan(rid)
    if plan["status"] != "APPROVED":
        fail("ERR_CATEGORY_PLAN_NOT_APPROVED",
             "the category plan is %s" % plan["status"])
    if data["expected_category_plan_version"] != plan["version"]:
        fail("ERR_STALE_CATEGORY_PLAN_VERSION",
             "expected_category_plan_version does not match the stored version")
    if plan["reforecast_round"] >= calc.REFORECAST_ROUND_CAP:
        fail("ERR_REFORECAST_ROUND_LIMIT", "the reforecast round cap has been reached")
    for cycle in store.plan_cycles(plan["id"]):
        if cycle["status"] in ("OPEN", "DECIDED"):
            fail("ERR_INVALID_STATE", "a reforecast cycle of this plan is still live")
    cycle = svc.open_cycle(plan, "DIRECTOR_REQUEST")
    return respond(public(cycle), 201)


@bp.get("/otb/reforecast-cycles/<rid>")
def read_cycle(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_cycle(rid)))


@bp.get("/otb/reforecast-cycles")
def list_cycles():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.cycles.values()))
    rows = _filter(rows, "category_plan_id")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


@bp.post("/otb/reforecast-cycles/<rid>/close")
def close_cycle(rid):
    auth([ROLE_DIRECTOR])
    parse_input([])
    cycle = store.get_cycle(rid)
    if cycle["status"] not in ("OPEN", "DECIDED"):
        fail("ERR_INVALID_STATE", "a %s cycle cannot be closed" % cycle["status"])
    for decision in store.cycle_decisions(cycle["id"]):
        if decision["status"] == "PROPOSED":
            fail("ERR_OPEN_DECISIONS_REMAIN",
                 "a decision of this cycle is still PROPOSED")
    cycle["status"] = "CLOSED"
    touch(cycle)
    return respond(public(cycle))


# ---------------------------------------------------------------------------
# Chase-or-cancel decisions
# ---------------------------------------------------------------------------
DECISION_FIELDS = [
    F("reforecast_cycle_id", "str", min_len=1),
    F("assortment_item_id", "str", min_len=1),
    F("action", "enum", enum=["CHASE", "CANCEL", "HOLD"]),
    F("requested_units", "int", minimum=0),
    F("rationale", "str", min_len=1, max_len=400),
]


@bp.post("/otb/chase-cancel-decisions")
def create_decision():
    user_id, _ = auth([ROLE_PLANNER, ROLE_BUYER])
    data = parse_input(DECISION_FIELDS)
    if data["action"] == "HOLD" and data["requested_units"] != 0:
        fail("ERR_INVALID_REQUEST", "requested_units must be 0 when action is HOLD")
    cycle = store.get_cycle(data["reforecast_cycle_id"])
    store.get_item(data["assortment_item_id"])
    if cycle["status"] == "DECIDED":
        plan = db.plans.get(cycle["category_plan_id"])
        if plan["status"] != "REFORECAST_OPEN":
            fail("ERR_INVALID_STATE",
                 "the parent category plan is %s" % plan["status"])
        cycle["status"] = "OPEN"
        touch(cycle)
    elif cycle["status"] != "OPEN":
        fail("ERR_INVALID_STATE",
             "a decision cannot be proposed into a %s cycle" % cycle["status"])
    row = make_row(
        proposed_by_user_id=user_id,
        approved_units=None,
        status="PROPOSED",
        **data)
    db.decisions[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/chase-cancel-decisions/<rid>")
def read_decision(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_decision(rid)))


@bp.get("/otb/chase-cancel-decisions")
def list_decisions():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.decisions.values()))
    rows = _filter(rows, "reforecast_cycle_id")
    rows = _filter(rows, "assortment_item_id")
    rows = _filter(rows, "action")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


def _adjudication_gates(decision, user_id):
    if decision.get("proposed_by_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the adjudicating operator proposed this decision")
    if decision["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "a %s decision cannot be adjudicated" % decision["status"])
    cycle = store.get_cycle(decision["reforecast_cycle_id"])
    if cycle["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "the parent cycle is %s" % cycle["status"])
    return cycle


@bp.post("/otb/chase-cancel-decisions/<rid>/approve")
def approve_decision(rid):
    user_id, _ = auth([ROLE_DIRECTOR])
    parse_input([F("decision_note", "str", required=False, max_len=1000)])
    decision = store.get_decision(rid)
    cycle = _adjudication_gates(decision, user_id)
    item = db.items.get(decision["assortment_item_id"])
    if item["status"] != "IN_SEASON":
        fail("ERR_INVALID_STATE", "the referenced item is %s" % item["status"])
    plan = db.plans.get(cycle["category_plan_id"])
    action = decision["action"]
    if action == "HOLD":
        decision["approved_units"] = 0
    elif action == "CHASE":
        approved, touched = svc.chase_allocation(plan, item, decision["requested_units"])
        if approved <= 0:
            fail("ERR_NO_FEASIBLE_RECEIPT_MONTH",
                 "no candidate plan month can fund a single unit")
        decision["approved_units"] = approved
        item["status"] = "CHASED"
        item["planned_units"] = (item["planned_units"] or 0) + approved
        touch(item)
        for month in touched:
            svc.recompute_month_buckets(month, plan)
        svc.recompute_plan_posture(plan)
    else:
        approved, touched = svc.cancel_allocation(item, decision["requested_units"])
        decision["approved_units"] = approved
        if approved > 0:
            item["status"] = "CANCELLED_IN_SEASON"
            item["planned_units"] = (item["planned_units"] or 0) - approved
            touch(item)
        for month in touched:
            svc.recompute_month_buckets(month, plan)
        svc.recompute_plan_posture(plan)
    decision["status"] = "APPROVED"
    touch(decision)
    svc.bubble_cycle(cycle)
    return respond(public(decision))


@bp.post("/otb/chase-cancel-decisions/<rid>/reject")
def reject_decision(rid):
    user_id, _ = auth([ROLE_DIRECTOR])
    parse_input([F("decision_note", "str", required=False, max_len=1000)])
    decision = store.get_decision(rid)
    cycle = _adjudication_gates(decision, user_id)
    decision["status"] = "REJECTED"
    decision["approved_units"] = 0
    touch(decision)
    svc.bubble_cycle(cycle)
    return respond(public(decision))
