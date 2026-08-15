"""Supplier contracts (PRD §3.3)."""
from flask import Blueprint

from db import db, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_STALE_CONTRACT_VERSION,
    ERR_AMENDMENT_BELOW_COMMITTED,
    ERR_OPEN_ORDERS_EXIST,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES
from routes.pools import GARMENT_TYPES
from services.orders import units_committed_map, units_committed_list
from util import is_int, is_pct, parse_date

bp = Blueprint("contracts", __name__)


def _validate_caps(caps):
    if not isinstance(caps, list):
        return None
    out = []
    for cap in caps:
        if not isinstance(cap, dict):
            return None
        if cap.get("garment_type") not in GARMENT_TYPES:
            return None
        if not is_int(cap.get("max_units")) or cap["max_units"] < 0:
            return None
        out.append({"garment_type": cap["garment_type"], "max_units": cap["max_units"]})
    return out


def _serialize_contract(contract):
    return serialize(contract, {"units_committed": units_committed_list(contract)})


@bp.post("/supplier-contracts")
@endpoint("TeamAdmin")
def create_contract(ctx):
    b = ctx.body
    vendor_name = b.get("vendor_name")
    season_label = b.get("season_label")
    start_on = parse_date(b.get("start_on"))
    end_on = parse_date(b.get("end_on"))
    caps = _validate_caps(b.get("allocation_caps"))
    lead_time = b.get("default_lead_time_days")
    rebate = b.get("contract_rebate_pct", 0)
    if not isinstance(vendor_name, str) or not vendor_name:
        raise_err(ERR_INVALID_REQUEST, "vendor_name is required")
    if not isinstance(season_label, str) or not season_label:
        raise_err(ERR_INVALID_REQUEST, "season_label is required")
    if start_on is None or end_on is None:
        raise_err(ERR_INVALID_REQUEST, "start_on/end_on must be YYYY-MM-DD dates")
    if caps is None:
        raise_err(ERR_INVALID_REQUEST, "allocation_caps invalid")
    if not is_int(lead_time) or lead_time <= 0:
        raise_err(ERR_INVALID_REQUEST, "default_lead_time_days must be an integer > 0")
    if not is_pct(rebate):
        raise_err(ERR_INVALID_REQUEST, "contract_rebate_pct must be within 0..1")
    contract = stamp(
        {
            "vendor_name": vendor_name,
            "season_label": season_label,
            "status": "DRAFT",
            "start_on": start_on.isoformat(),
            "end_on": end_on.isoformat(),
            "allocation_caps": caps,
            "default_lead_time_days": lead_time,
            "contract_rebate_pct": rebate,
        }
    )
    db.contracts[contract["id"]] = contract
    return success(_serialize_contract(contract), 201)


@bp.get("/supplier-contracts/<contract_id>")
@endpoint(*ALL_ROLES)
def get_contract(ctx, contract_id):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "contract not found")
    return success(_serialize_contract(contract))


@bp.post("/supplier-contracts/<contract_id>/activate")
@endpoint("TeamAdmin")
def activate_contract(ctx, contract_id):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "contract not found")
    if contract["status"] != "DRAFT":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "activate requires DRAFT")
    if not contract["allocation_caps"]:
        raise_err(ERR_INVALID_REQUEST, "allocation_caps must be non-empty to activate")
    if contract["start_on"] > contract["end_on"]:
        raise_err(ERR_INVALID_REQUEST, "start_on must be on or before end_on")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success(_serialize_contract(contract))


@bp.post("/supplier-contracts/<contract_id>/amendments")
@endpoint("TeamAdmin")
def amend_contract(ctx, contract_id):
    b = ctx.body
    caps = _validate_caps(b.get("allocation_caps"))
    expected = b.get("expected_supplier_contract_version")
    if caps is None:
        raise_err(ERR_INVALID_REQUEST, "allocation_caps invalid")
    if not is_int(expected):
        raise_err(
            ERR_INVALID_REQUEST, "expected_supplier_contract_version must be an integer"
        )
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "contract not found")
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "amendment requires ACTIVE contract")
    if expected != contract["version"]:
        raise_err(ERR_STALE_CONTRACT_VERSION, "expected_supplier_contract_version is stale")
    committed = units_committed_map(contract)
    for cap in caps:
        if cap["max_units"] < committed.get(cap["garment_type"], 0):
            raise_err(ERR_AMENDMENT_BELOW_COMMITTED, "amended cap below committed units")
    contract["allocation_caps"] = caps
    touch(contract)
    return success(_serialize_contract(contract))


@bp.post("/supplier-contracts/<contract_id>/close")
@endpoint("TeamAdmin")
def close_contract(ctx, contract_id):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "contract not found")
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "close requires ACTIVE contract")
    if any(
        o
        for o in db.orders.values()
        if o["supplier_contract_id"] == contract_id
        and o["status"] in ("SUBMITTED", "PARTIALLY_RECEIVED")
    ):
        raise_err(ERR_OPEN_ORDERS_EXIST, "contract has open orders")
    contract["status"] = "CLOSED"
    touch(contract)
    return success(_serialize_contract(contract))
