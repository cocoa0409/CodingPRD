"""FuelSupplyContract endpoints and the supply-interruption cascade (PRD 3.2)."""

from flask import Blueprint

import enums
import services as svc
from db import base_record, store
from errors import fail
from middleware import endpoint, paginate
from validators import (get_enum, get_num, get_str, json_body, present,
                        query_enum)

bp = Blueprint("fuel", __name__, url_prefix="/district-energy")

READERS = ("SystemController", "DispatchOperator", "NetworkEngineer", "BillingAnalyst")

LEGAL_STATUS = {
    ("ACTIVE", "SUSPENDED"): svc.cascade_contract_suspended,
    ("SUSPENDED", "ACTIVE"): svc.cascade_contract_reinstated,
    ("ACTIVE", "EXPIRED"): svc.cascade_contract_expired,
    ("SUSPENDED", "EXPIRED"): svc.cascade_contract_expired,
}


@endpoint(bp, "/fuel-supply-contracts", ["POST"], ["SystemController"], status=201)
def create_contract():
    body = json_body()
    supplier_code = get_str(body, "supplier_code")
    fuel_type = get_enum(body, "fuel_type", enums.FUEL_TYPE)
    contracted_energy = get_num(body, "contracted_energy_mwh_per_year", gt=0)
    price_per_mwh = get_num(body, "price_per_mwh")
    delivery_firmness = get_enum(body, "delivery_firmness", enums.DELIVERY_FIRMNESS)

    svc.require_unique_code("fuel_contracts", "supplier_code", supplier_code)

    contract = base_record()
    contract.update({
        "supplier_code": supplier_code,
        "fuel_type": fuel_type,
        "contracted_energy_mwh_per_year": contracted_energy,
        "price_per_mwh": price_per_mwh,
        "delivery_firmness": delivery_firmness,
        "status": "ACTIVE",
    })
    store.fuel_contracts[contract["id"]] = contract
    return contract


@endpoint(bp, "/fuel-supply-contracts", ["GET"], READERS)
def list_contracts():
    filters = {}
    fuel_type = query_enum("fuel_type", enums.FUEL_TYPE)
    status = query_enum("status", enums.CONTRACT_STATUS)
    firmness = query_enum("delivery_firmness", enums.DELIVERY_FIRMNESS)
    if fuel_type is not None:
        filters["fuel_type"] = fuel_type
    if status is not None:
        filters["status"] = status
    if firmness is not None:
        filters["delivery_firmness"] = firmness
    return paginate(svc.where("fuel_contracts", **filters))


@endpoint(bp, "/fuel-supply-contracts/<contract_id>", ["GET"], READERS)
def get_contract(contract_id):
    return svc.path_get("fuel_contracts", contract_id)


@endpoint(bp, "/fuel-supply-contracts/<contract_id>/status", ["POST"],
          ["SystemController"])
def set_contract_status(contract_id):
    body = json_body()
    status = get_enum(body, "status", enums.CONTRACT_STATUS)
    if present(body, "reason"):
        get_str(body, "reason", min_len=0)

    contract = svc.path_get("fuel_contracts", contract_id)

    cascade = LEGAL_STATUS.get((contract["status"], status))
    if cascade is None:
        fail("ERR_AVAILABILITY_STATE_INVALID",
             "a supply contract in status '%s' cannot move to '%s'"
             % (contract["status"], status))
    cascade(contract)
    return contract
