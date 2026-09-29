"""Mine registration, the two derating dimensions and the capacity view."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from errors import ERR_INSPECTION_NOT_FOUND, fail, invalid
from middleware import auth, require_distinct_actor
from services import calc, cascade, derive, serialize
from util import body, enum, filter_str, number, require, state_code, text

bp = Blueprint("mines", __name__)

HOIST_STATES = ("HOIST_AVAILABLE", "HOIST_DERATED", "HOIST_DOWN")
COMPLIANCE_ACTIONS = {"CITE": "CITED", "WITHDRAW": "WITHDRAWAL_ORDER",
                      "CLEAR": "COMPLIANT"}
HOIST_RANK = {"HOIST_AVAILABLE": 2, "HOIST_DERATED": 1, "HOIST_DOWN": 0}


@bp.post("/salt/mines")
@auth("MinePlanner")
def create_mine():
    payload = body()
    require(payload, ["name", "state_code", "rated_hoist_tons_per_day"])
    name = text(payload, "name", minlen=1, maxlen=120)
    code = state_code(payload)
    rated = number(payload, "rated_hoist_tons_per_day", gt=0)
    plan_version = 1
    if "ground_control_plan_version" in payload and payload["ground_control_plan_version"] is not None:
        plan_version = number(payload, "ground_control_plan_version", minv=1,
                              integer=True)

    mine = db.stamp()
    mine.update({
        "name": name,
        "state_code": code,
        "rated_hoist_tons_per_day": rated,
        "ground_control_plan_version": plan_version,
        "hoist_state": "HOIST_AVAILABLE",
        "compliance_state": "COMPLIANT",
        "last_compliance_action_at": None,
    })
    derive.refresh_mine_capacity(mine)
    store.mines[mine["id"]] = mine
    return response.created(serialize.mine_json(mine))


@bp.get("/salt/mines/<mine_id>")
@auth()
def read_mine(mine_id):
    return response.ok(serialize.mine_json(derive.get_mine(mine_id)))


@bp.get("/salt/mines")
@auth()
def list_mines():
    rows = list(store.mines.values())
    code = filter_str("state_code")
    hoist_state = filter_str("hoist_state")
    compliance_state = filter_str("compliance_state")
    if code is not None:
        rows = [r for r in rows if r["state_code"] == code]
    if hoist_state is not None:
        rows = [r for r in rows if r["hoist_state"] == hoist_state]
    if compliance_state is not None:
        rows = [r for r in rows if r["compliance_state"] == compliance_state]
    return response.page(db.by_seq(rows), serialize.mine_json)


@bp.get("/salt/mines/<mine_id>/hoist-capacity")
@auth("MinePlanner", "GroundControlEngineer", "LogisticsPlanner",
      "ComplianceOfficer")
def read_hoist_capacity(mine_id):
    mine = derive.get_mine(mine_id)
    return response.ok(serialize.hoist_capacity_json(mine))


@bp.post("/salt/mines/<mine_id>/hoist-status")
@auth("MinePlanner")
def set_hoist_status(mine_id):
    payload = body()
    require(payload, ["hoist_state"])
    target = enum(payload, "hoist_state", HOIST_STATES)
    mine = derive.get_mine(mine_id)
    current = mine["hoist_state"]
    if target == current:
        invalid("hoist_state must differ from the value the mine currently holds")

    mine["hoist_state"] = target
    cascade.recompute_mine_capacity(mine)
    if HOIST_RANK[target] < HOIST_RANK[current]:
        cascade.capacity_refit(mine)
    return response.ok(serialize.mine_json(mine))


@bp.post("/salt/mines/<mine_id>/compliance-action")
@auth("ComplianceOfficer")
def compliance_action(mine_id):
    payload = body()

    # stage 3 -- segregation of duties against the cited inspection
    raw_inspection = payload.get("inspection_id")
    if isinstance(raw_inspection, str) and raw_inspection in store.inspections:
        require_distinct_actor(
            store.inspections[raw_inspection]["inspector_user_id"],
            "the officer citing an inspection may not be its inspector")

    require(payload, ["action"])
    action = enum(payload, "action", tuple(COMPLIANCE_ACTIONS.keys()))
    mine = derive.get_mine(mine_id)
    if raw_inspection is not None:
        if not isinstance(raw_inspection, str) or raw_inspection not in store.inspections:
            fail(ERR_INSPECTION_NOT_FOUND,
                 "inspection %s was not found" % raw_inspection)

    target = COMPLIANCE_ACTIONS[action]
    current = mine["compliance_state"]
    if target == current:
        invalid("action must produce a compliance_state different from the current one")

    mine["compliance_state"] = target
    mine["last_compliance_action_at"] = db.now()
    cascade.recompute_mine_capacity(mine)
    derive.recompute_panel_reserves(mine)

    if target == "WITHDRAWAL_ORDER":
        cascade.hold_all_scheduled(mine, "GROUND_CONTROL")
    elif current == "COMPLIANT" and target == "CITED":
        cascade.capacity_refit(mine)
    return response.ok(serialize.mine_json(mine))
