"""ProductionAsset endpoints and manual availability declarations (PRD 3.3)."""

from flask import Blueprint

import enums
import services as svc
from db import base_record, store, touch
from errors import fail
from middleware import ALL_STAFF, endpoint, paginate
from validators import (bad, get_enum, get_num, get_str, json_body, present,
                        query_enum, query_str)

bp = Blueprint("assets", __name__, url_prefix="/district-energy")

LEGAL_AVAILABILITY = (
    ("AVAILABLE", "DERATED"),
    ("DERATED", "AVAILABLE"),
    ("AVAILABLE", "OUTAGE"),
    ("DERATED", "OUTAGE"),
    ("OUTAGE", "AVAILABLE"),
    ("OUTAGE", "DERATED"),
)


@endpoint(bp, "/production-assets", ["POST"], ["SystemController"], status=201)
def create_asset():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    code = get_str(body, "code")
    asset_type = get_enum(body, "asset_type", enums.ASSET_TYPE)
    rated_capacity_kw = get_num(body, "rated_capacity_kw", gt=0)
    marginal_cost = get_num(body, "marginal_cost_per_mwh")
    emission_factor = get_num(body, "emission_factor_kg_per_mwh")
    fuel_contract_id = get_str(body, "fuel_contract_id", required=False, default=None)
    derated_capacity_kw = get_num(body, "derated_capacity_kw", required=False,
                                  default=0.0, ge=0)
    min_stable_output_kw = get_num(body, "min_stable_output_kw", required=False,
                                   default=0.0, ge=0)
    storage_capacity_kwh = get_num(body, "storage_capacity_kwh", required=False,
                                   default=0.0, ge=0)
    state_of_charge_kwh = get_num(body, "state_of_charge_kwh", required=False,
                                  default=0.0, ge=0)
    if state_of_charge_kwh > storage_capacity_kwh:
        bad("field 'state_of_charge_kwh' must not exceed storage_capacity_kwh")

    loop = svc.fk_get("loops", loop_id)
    if fuel_contract_id is not None:
        svc.fk_get("fuel_contracts", fuel_contract_id)

    svc.require_unique_code("assets", "code", code, loop_id=loop["id"])

    asset = base_record()
    asset.update({
        "loop_id": loop["id"],
        "fuel_contract_id": fuel_contract_id,
        "code": code,
        "asset_type": asset_type,
        "rated_capacity_kw": rated_capacity_kw,
        "derated_capacity_kw": derated_capacity_kw,
        "min_stable_output_kw": min_stable_output_kw,
        "marginal_cost_per_mwh": marginal_cost,
        "emission_factor_kg_per_mwh": emission_factor,
        "storage_capacity_kwh": storage_capacity_kwh,
        "state_of_charge_kwh": state_of_charge_kwh,
        "availability_state": "AVAILABLE",
    })
    store.assets[asset["id"]] = asset
    return asset


@endpoint(bp, "/production-assets", ["GET"], ALL_STAFF)
def list_assets():
    filters = {}
    loop_id = query_str("loop_id")
    fuel_contract_id = query_str("fuel_contract_id")
    availability_state = query_enum("availability_state", enums.AVAILABILITY_STATE)
    asset_type = query_enum("asset_type", enums.ASSET_TYPE)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if fuel_contract_id is not None:
        filters["fuel_contract_id"] = fuel_contract_id
    if availability_state is not None:
        filters["availability_state"] = availability_state
    if asset_type is not None:
        filters["asset_type"] = asset_type
    return paginate(svc.where("assets", **filters))


@endpoint(bp, "/production-assets/<asset_id>", ["GET"], ALL_STAFF)
def get_asset(asset_id):
    return svc.path_get("assets", asset_id)


@endpoint(bp, "/production-assets/<asset_id>/availability", ["POST"],
          ["SystemController"])
def set_availability(asset_id):
    body = json_body()
    target = get_enum(body, "availability_state", enums.AVAILABILITY_STATE)
    derated = get_num(body, "derated_capacity_kw", required=False, default=None, ge=0)
    if present(body, "reason"):
        get_str(body, "reason", min_len=0)

    asset = svc.path_get("assets", asset_id)
    current = asset["availability_state"]

    if (current, target) not in LEGAL_AVAILABILITY:
        fail("ERR_AVAILABILITY_STATE_INVALID",
             "an asset in state '%s' cannot move to '%s'" % (current, target))

    # The DERATED gate is evaluated against the post-overwrite ceiling; nothing
    # is persisted when the gate rejects the transition.
    effective_derated = derated if derated is not None else asset["derated_capacity_kw"]
    if target == "DERATED" and not effective_derated > 0:
        fail("ERR_AVAILABILITY_STATE_INVALID",
             "an asset cannot be DERATED while its derated_capacity_kw is 0")
    if target == "AVAILABLE" and current == "OUTAGE":
        contract_id = asset.get("fuel_contract_id")
        if contract_id is not None:
            contract = store.fuel_contracts.get(contract_id)
            if contract is None or contract["status"] != "ACTIVE":
                fail("ERR_AVAILABILITY_STATE_INVALID",
                     "the asset's supply contract is not ACTIVE")

    if derated is not None:
        asset["derated_capacity_kw"] = derated
    asset["availability_state"] = target
    touch(asset)
    return asset
