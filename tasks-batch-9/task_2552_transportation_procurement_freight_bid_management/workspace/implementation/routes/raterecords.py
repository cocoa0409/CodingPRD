"""Rate loading, the go-live cutover and the tender log — PRD §3.8 and §3.9."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from services import contracts as contract_svc, lanes as lane_svc, tender

bp = Blueprint("raterecords", __name__)

TENDER_OUTCOMES = ("ACCEPTED", "REJECTED", "TIMEOUT")
LIVE_RECORD_STATUSES = ("LIVE", "AT_RISK")


@bp.get("/freight-procurement/rate-records/<record_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def get_record(record_id):
    return responses.ok(helpers.get_rate_record(record_id))


@bp.get("/freight-procurement/rate-records")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_records():
    rows = store.sorted_rows(store.rate_records.values())
    rows = helpers.filter_rows(rows, {
        "contract_id": "contract_id",
        "lane_id": "lane_id",
        "carrier_id": "carrier_id",
        "award_allocation_id": "award_allocation_id",
        "superseded_by_rate_record_id": "superseded_by_rate_record_id",
        "status": "status",
    })
    return responses.listing(rows)


@bp.post("/freight-procurement/rate-records/<record_id>/load")
@auth.roles_required("ContractAdmin")
def load_record(record_id):
    record = helpers.get_rate_record(record_id)
    v.body()

    if record["status"] != "STAGED":
        raise ApiError("ERR_RATE_RECORD_NOT_LOADED")

    carrier = store.carriers.get(record["carrier_id"])
    if carrier is not None:
        helpers.check_fitness(carrier, require_standing=False)

    if contract_svc.interval_overlaps(record, record["effective_from"],
                                     record["effective_to"]):
        raise ApiError("ERR_RATE_INTERVAL_OVERLAP")

    record["status"] = "LOADED"
    record["loaded_at"] = store.now_iso()
    store.touch(record)

    contract = store.contracts.get(record["contract_id"])
    if contract is not None and contract["rate_load_status"] == "STAGED":
        contract["rate_load_status"] = "LOADED"
        store.touch(contract)
    return responses.ok(record)


@bp.post("/freight-procurement/rate-records/<record_id>/go-live")
@auth.roles_required("ContractAdmin")
def go_live(record_id):
    record = helpers.get_rate_record(record_id)
    v.body()
    contract = store.contracts.get(record["contract_id"])

    if record["status"] != "LOADED":
        raise ApiError("ERR_RATE_RECORD_NOT_LOADED")
    if contract is None or contract["signature_status"] != "FULLY_SIGNED":
        raise ApiError("ERR_CONTRACT_NOT_FULLY_SIGNED")

    carrier = store.carriers.get(record["carrier_id"])
    if carrier is not None:
        helpers.check_fitness(carrier)

    # The half-open interval: at or after effective_from, strictly before effective_to.
    now = store.now()
    if not (store.dt_of(record["effective_from"]) <= now
            < store.dt_of(record["effective_to"])):
        raise ApiError("ERR_RATE_NOT_IN_EFFECTIVE_WINDOW")

    # Link 1 — the record goes live.
    record["status"] = "LIVE"
    record["live_at"] = store.now_iso()
    store.touch(record)

    # Link 2 — the allocation it implements activates, and the carrier's rollups follow.
    allocation = store.allocations.get(record["award_allocation_id"])
    if allocation is not None and allocation["status"] == "EXECUTED":
        allocation["status"] = "ACTIVE"
        store.touch(allocation)
        if carrier is not None:
            contract_svc.recompute_carrier_commitments(carrier)
            store.touch(carrier)

    # Link 3 — the contract's rate-loading dimension.
    if contract["rate_load_status"] == "LOADED":
        contract["rate_load_status"] = "LIVE"
        store.touch(contract)

    # Link 4 — on the event's first live rate the event itself goes terminal.
    event = helpers.event_of(contract)
    if event is not None and event["status"] == "AWARDED":
        event["status"] = "LIVE"
        lane_svc.recompute_coverage(event)
        store.touch(event)
    return responses.ok(record)


@bp.post("/freight-procurement/rate-records/<record_id>/tender-events")
@auth.roles_required("ProcurementAnalyst", "ContractAdmin")
def append_tender(record_id):
    record = helpers.get_rate_record(record_id)
    payload = v.body()
    outcome = v.enum_field(payload, "outcome", TENDER_OUTCOMES)
    load_reference = v.string_field(payload, "load_reference", min_len=1, max_len=32)
    reject_reason = v.string_field(payload, "reject_reason", required=False)

    if record["status"] not in LIVE_RECORD_STATUSES:
        raise ApiError("ERR_RATE_RECORD_NOT_LIVE")

    # Rung 13 — load_reference is unique within its rate record; the same reference under
    # a different record is legal.
    for other in store.tender_events.values():
        if (other["rate_record_id"] == record["id"]
                and other["load_reference"] == load_reference):
            raise ApiError("ERR_DUPLICATE_LOAD_REFERENCE")

    event_row = store.new_event_row(
        rate_record_id=record["id"],
        outcome=outcome,
        load_reference=load_reference,
        reject_reason=reject_reason,
        position_used=record["routing_position"],
        tendered_at=store.now_iso(),
    )
    store.tender_events[event_row["id"]] = event_row

    tender.recompute_metrics(record)
    tender.apply_risk_determination(record)
    store.touch(record)
    return responses.created(event_row)


@bp.get("/freight-procurement/rate-records/<record_id>/tender-events")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_tenders(record_id):
    record = helpers.get_rate_record(record_id)
    return responses.listing(tender.record_tenders(record["id"]))
