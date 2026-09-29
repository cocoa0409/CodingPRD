"""Contract execution and rate staging — PRD §3.8."""
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError, bad_request
from numeric import q2, q4
from services import contracts as contract_svc

bp = Blueprint("contracts", __name__)

ROUTING_POSITIONS = ("PRIMARY", "BACKUP_1", "BACKUP_2")


@bp.get("/freight-procurement/contracts/<contract_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def get_contract(contract_id):
    return responses.ok(helpers.get_contract(contract_id))


@bp.get("/freight-procurement/contracts")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_contracts():
    rows = store.sorted_rows(store.contracts.values())
    rows = helpers.filter_rows(rows, {
        "bid_event_id": "bid_event_id",
        "carrier_id": "carrier_id",
        "status": "status",
        "signature_status": "signature_status",
    })
    return responses.listing(rows)


@bp.post("/freight-procurement/contracts/<contract_id>/carrier-signature")
@auth.roles_required("CarrierRep")
def carrier_signature(contract_id):
    contract = helpers.get_contract(contract_id)
    v.body()
    auth.own_carrier_or_raise(contract["carrier_id"])

    if contract["signature_status"] not in ("PENDING_BOTH", "PENDING_CARRIER"):
        raise ApiError("ERR_CONTRACT_NOT_FULLY_SIGNED")

    if contract["signature_status"] == "PENDING_BOTH":
        contract["signature_status"] = "PENDING_SHIPPER"
    else:
        contract["signature_status"] = "FULLY_SIGNED"
        if contract["status"] == "DRAFT":
            contract["status"] = "EXECUTED"
    contract["carrier_signed_by_user_id"] = auth.actor()
    contract["carrier_signed_at"] = store.now_iso()
    store.touch(contract)
    return responses.ok(contract)


@bp.post("/freight-procurement/contracts/<contract_id>/shipper-signature")
@auth.roles_required("ContractAdmin")
def shipper_signature(contract_id):
    contract = helpers.get_contract(contract_id)
    v.body()

    # Rung 7 — the operator who approved an award may never countersign the resulting
    # contract, and the bar compares identifiers rather than roles (PRD §2.11).
    actor = auth.actor()
    for allocation in store.allocations.values():
        if (allocation["bid_event_id"] == contract["bid_event_id"]
                and allocation["carrier_id"] == contract["carrier_id"]
                and allocation.get("approved_by_user_id") == actor):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if contract["signature_status"] not in ("PENDING_BOTH", "PENDING_SHIPPER"):
        raise ApiError("ERR_CONTRACT_NOT_FULLY_SIGNED")

    if contract["signature_status"] == "PENDING_BOTH":
        contract["signature_status"] = "PENDING_CARRIER"
    else:
        contract["signature_status"] = "FULLY_SIGNED"
        if contract["status"] == "DRAFT":
            contract["status"] = "EXECUTED"
    contract["shipper_signed_by_user_id"] = actor
    contract["shipper_signed_at"] = store.now_iso()
    store.touch(contract)
    return responses.ok(contract)


@bp.post("/freight-procurement/contracts/<contract_id>/rate-records")
@auth.roles_required("ContractAdmin")
def stage_rate_record(contract_id):
    contract = helpers.get_contract(contract_id)
    payload = v.body()

    lane_id = v.id_field(payload, "lane_id")
    carrier_id = v.id_field(payload, "carrier_id")
    allocation_id = v.id_field(payload, "award_allocation_id")
    position = v.enum_field(payload, "routing_position", ROUTING_POSITIONS)
    rate = v.dec_field(payload, "rate_per_mile", exclusive_min=True)
    fuel_included = v.bool_field(payload, "fuel_surcharge_included")
    effective_from = v.dt_field(payload, "effective_from")
    effective_to = v.dt_field(payload, "effective_to")
    v.interval(effective_from, effective_to, "effective_from", "effective_to")
    volume = v.int_field(payload, "committed_volume_loads", minimum=1)

    # Rung 5 — body foreign keys in the order the fields are declared.
    lane = helpers.get_lane(lane_id)
    helpers.get_carrier(carrier_id)
    allocation = helpers.get_allocation(allocation_id)

    if allocation["routing_position"] != position:
        raise bad_request("routing_position must match the allocation's own "
                          "routing_position.")

    record = store.new_row(
        contract_id=contract["id"],
        lane_id=lane["id"],
        carrier_id=carrier_id,
        award_allocation_id=allocation["id"],
        superseded_by_rate_record_id=None,
        routing_position=position,
        rate_per_mile=q4(rate),
        fuel_surcharge_included=fuel_included,
        effective_from=effective_from,
        effective_to=effective_to,
        committed_volume_loads=volume,
        committed_value_usd=Decimal("0.00"),
        status="STAGED",
        tender_count=0,
        rejection_count=0,
        rejection_pct=Decimal("0.00"),
        acceptance_pct=Decimal("100.00"),
        loaded_at=None,
        live_at=None,
    )
    event = helpers.event_of(contract)
    record["committed_value_usd"] = contract_svc.record_committed_value(record, event)
    store.rate_records[record["id"]] = record

    contract_svc.recompute_rate_record_count(contract)
    if contract["rate_load_status"] == "NOT_STAGED":
        contract["rate_load_status"] = "STAGED"
    contract_svc.recompute_committed_value(contract, event)
    store.touch(contract)
    return responses.created(record)
