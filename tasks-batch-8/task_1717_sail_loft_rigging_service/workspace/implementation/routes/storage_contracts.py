"""StorageContract endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles, require_owner
from response import success_object, success_list
from services import domain, calculations as calc

bp = Blueprint("storage_contracts", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
WASH_ITEMS = ("MAIN_WASH", "GENOA_WASH", "SPINNAKER_WASH", "RIG_WASH")


@bp.post("/lofts/boats/<boatId>/storage-contracts")
def create_contract(boatId):
    require_roles("LoftManager")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    season_code = util.as_string(util.require_field(body, "season_code"), "season_code")
    wash_item_codes = util.as_enum_array(util.opt_field(body, "wash_item_codes", []), "wash_item_codes", WASH_ITEMS)
    contract = util.stamp_new({
        "boat_id": boat["id"],
        "season_code": season_code,
        "wash_item_codes": wash_item_codes,
        "quoted_storage_fee_cents": 0,
        "contract_status": "ENROLLED",
    })
    db.storage_contracts[contract["id"]] = contract
    return success_object(domain.serialize(contract), 201)


@bp.get("/lofts/boats/<boatId>/storage-contracts")
def list_boat_contracts(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [c for c in db.storage_contracts.values() if c["boat_id"] == boatId]
    items = util.filter_exact(items, "contract_status", request.args.get("contract_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], limit, offset, total)


@bp.get("/lofts/storage-contracts")
def list_contracts():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.storage_contracts.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "contract_status", request.args.get("contract_status"))
    items = util.filter_exact(items, "season_code", request.args.get("season_code"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], limit, offset, total)


@bp.get("/lofts/storage-contracts/<contractId>")
def get_contract(contractId):
    require_roles(*READ_ROLES)
    contract = domain.get_contract_or_404(contractId)
    return success_object(domain.serialize(contract))


def _get_scoped_contract(boatId, contractId):
    boat = domain.get_boat_or_404(boatId)
    contract = domain.get_contract_or_404(contractId)
    domain.check_child_of(contract, "boat_id", boat["id"])
    return boat, contract


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/receive")
def receive_contract(boatId, contractId):
    require_roles("LoftManager")
    boat, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "ENROLLED":
        raise errors.invalid_state(f"Contract must be ENROLLED to receive (is {contract['contract_status']})")
    contract["quoted_storage_fee_cents"] = calc.storage_fee(
        contract.get("wash_item_codes", []), boat["hull_length_m"]
    )
    contract["contract_status"] = "RECEIVED"
    util.touch(contract)
    return success_object(domain.serialize(contract))


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/complete-wash")
def complete_wash(boatId, contractId):
    require_roles("LoftManager")
    _, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "RECEIVED":
        raise errors.invalid_state(f"Contract must be RECEIVED to complete-wash (is {contract['contract_status']})")
    contract["contract_status"] = "WASHED"
    util.touch(contract)
    return success_object(domain.serialize(contract))


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/rack-store")
def rack_store(boatId, contractId):
    require_roles("LoftManager")
    _, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "WASHED":
        raise errors.invalid_state(f"Contract must be WASHED to rack-store (is {contract['contract_status']})")
    contract["contract_status"] = "STORED"
    util.touch(contract)
    return success_object(domain.serialize(contract))


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/stage-delivery")
def stage_delivery(boatId, contractId):
    require_roles("LoftManager")
    _, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "STORED":
        raise errors.invalid_state(f"Contract must be STORED to stage-delivery (is {contract['contract_status']})")
    contract["contract_status"] = "OUT_FOR_DELIVERY"
    util.touch(contract)
    return success_object(domain.serialize(contract))


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/confirm-return")
def confirm_return(boatId, contractId):
    user_id, _ = require_roles("Customer")
    boat, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "OUT_FOR_DELIVERY":
        raise errors.invalid_state(f"Contract must be OUT_FOR_DELIVERY to confirm-return (is {contract['contract_status']})")
    require_owner(user_id, boat["customer_id"])
    customer = domain.get_customer_or_404(boat["customer_id"])
    customer["outstanding_balance_cents"] += contract["quoted_storage_fee_cents"]
    util.touch(customer)
    contract["contract_status"] = "RETURNED"
    util.touch(contract)
    return success_object(domain.serialize(contract))


@bp.post("/lofts/boats/<boatId>/storage-contracts/<contractId>/cancel")
def cancel_contract(boatId, contractId):
    require_roles("LoftManager")
    _, contract = _get_scoped_contract(boatId, contractId)
    if contract["contract_status"] != "ENROLLED":
        raise errors.invalid_state(f"Contract must be ENROLLED to cancel (is {contract['contract_status']})")
    contract["contract_status"] = "CANCELLED"
    util.touch(contract)
    return success_object(domain.serialize(contract))
