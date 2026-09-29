"""Depots, capacity revision and storm posture."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from errors import invalid
from middleware import auth, require_depot_ownership
from services import derive, serialize
from util import body, enum, filter_str, number, present, require, state_code, text

bp = Blueprint("depots", __name__)

DEPOT_STATES = ("OPEN", "SURGE", "CLOSED")


@bp.post("/salt/depots")
@auth("LogisticsPlanner")
def create_depot():
    payload = body()
    require(payload, ["name", "state_code", "covered_capacity_tons",
                      "open_pad_capacity_tons", "loadout_rate_tons_per_hour",
                      "outbound_freight_rate_per_ton"])
    name = text(payload, "name", minlen=1, maxlen=120)
    code = state_code(payload)
    covered = number(payload, "covered_capacity_tons", minv=0)
    open_pad = number(payload, "open_pad_capacity_tons", minv=0)
    loadout = number(payload, "loadout_rate_tons_per_hour", gt=0)
    freight = number(payload, "outbound_freight_rate_per_ton", minv=0)

    depot = db.stamp()
    depot.update({
        "name": name,
        "state_code": code,
        "covered_capacity_tons": covered,
        "open_pad_capacity_tons": open_pad,
        "loadout_rate_tons_per_hour": loadout,
        "outbound_freight_rate_per_ton": freight,
        "depot_state": "OPEN",
        "storm_state_set_by_user_id": None,
    })
    store.depots[depot["id"]] = depot
    return response.created(serialize.depot_json(depot))


@bp.get("/salt/depots/<depot_id>")
@auth()
def read_depot(depot_id):
    return response.ok(serialize.depot_json(derive.get_depot(depot_id)))


@bp.get("/salt/depots")
@auth()
def list_depots():
    rows = list(store.depots.values())
    for name in ("state_code", "depot_state"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.depot_json)


@bp.get("/salt/depots/<depot_id>/storage-posture")
@auth("LogisticsPlanner", "DepotManager", "ContractAdministrator")
def read_storage_posture(depot_id):
    depot = derive.get_depot(depot_id)
    return response.ok(serialize.storage_posture_json(depot))


@bp.patch("/salt/depots/<depot_id>")
@auth("LogisticsPlanner", "DepotManager")
def patch_depot(depot_id):
    require_depot_ownership(depot_id)
    payload = body()
    covered = number(payload, "covered_capacity_tons", minv=0, required=False)
    open_pad = number(payload, "open_pad_capacity_tons", minv=0, required=False)
    loadout = number(payload, "loadout_rate_tons_per_hour", gt=0, required=False)
    freight = number(payload, "outbound_freight_rate_per_ton", minv=0,
                     required=False)

    depot = derive.get_depot(depot_id)
    if covered is not None:
        depot["covered_capacity_tons"] = covered
    if open_pad is not None:
        depot["open_pad_capacity_tons"] = open_pad
    if loadout is not None:
        depot["loadout_rate_tons_per_hour"] = loadout
    if freight is not None:
        depot["outbound_freight_rate_per_ton"] = freight

    derive.maybe_auto_surge(depot)
    touch(depot)
    return response.ok(serialize.depot_json(depot))


@bp.post("/salt/depots/<depot_id>/posture")
@auth("DepotManager", "LogisticsPlanner")
def set_posture(depot_id):
    require_depot_ownership(depot_id)
    payload = body()
    require(payload, ["depot_state"])
    target = enum(payload, "depot_state", DEPOT_STATES)
    depot = derive.get_depot(depot_id)
    if target == depot["depot_state"]:
        invalid("depot_state must differ from the value the depot currently holds")

    depot["depot_state"] = target
    depot["storm_state_set_by_user_id"] = g.user_id
    touch(depot)
    return response.ok(serialize.depot_json(depot))
