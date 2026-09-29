"""Harvest-year contracts, their lifecycle and the storage ledger."""

from decimal import Decimal

from flask import Blueprint, request

import domain
from auth import ALL_ROLES, CLIENT_REP, COMPLIANCE_OFFICER, FACILITY_ADMIN, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_ALLOCATIONS_OUTSTANDING,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_STALE_CONTRACT_VERSION,
)
from helpers import declared, run_list
from store import db, iso, new_entity, parse_iso, touch
from validation import v_datetime, v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("contracts", __name__)

CONTRACT_ACTIONS = {
    "SUBMIT": [FACILITY_ADMIN],
    "REVISE": [FACILITY_ADMIN],
    "ACTIVATE": [FACILITY_ADMIN],
    "SUSPEND": [FACILITY_ADMIN],
    "REINSTATE": [FACILITY_ADMIN],
    "TERMINATE": [FACILITY_ADMIN],
}

STORAGE_VARIANTS = ("OCCUPANCY", "VESSEL_FOOTPRINT")


@bp.route("/contracts", methods=["POST"])
def create_contract():
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    client_id = v_string(body, "client_id")
    harvest_year = v_int(body, "harvest_year", ge=2020, le=2035)
    committed_tons = v_number(body, "committed_tons", gt=0)
    tank_gallons = v_number(body, "tank_gallons_entitled", gt=0)
    barrel_slots = v_int(body, "barrel_slots_entitled", ge=0)
    crush_rate = v_int(body, "crush_rate_cents_per_ton", gt=0)
    storage_rate = v_int(body, "storage_rate_cents_per_gallon_month", gt=0)
    labor_rate = v_int(body, "labor_rate_cents_per_hour", gt=0)
    eff_from_raw, eff_from = v_datetime(body, "effective_from")
    eff_to_raw, eff_to = v_datetime(body, "effective_to")

    domain.get_client(client_id)

    contract = new_entity({
        "client_id": client_id,
        "harvest_year": harvest_year,
        "committed_tons": committed_tons,
        "tank_gallons_entitled": tank_gallons,
        "barrel_slots_entitled": barrel_slots,
        "crush_rate_cents_per_ton": crush_rate,
        "storage_rate_cents_per_gallon_month": storage_rate,
        "labor_rate_cents_per_hour": labor_rate,
        "effective_from": eff_from_raw,
        "effective_to": eff_to_raw,
        "status": "DRAFT",
        "tons_received": D(0),
        "gallons_allocated": D(0),
        "barrel_slots_used": 0,
        "billed_total_cents": 0,
        "storage_billed_through": None,
        "_eff_from_dt": eff_from,
        "_eff_to_dt": eff_to,
        "_billed_through_dt": None,
    })
    db.contracts[contract["id"]] = contract
    return respond(domain.serialize(contract), 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    ctx = guard(ALL_ROLES, read_body=False)
    contract = domain.get_contract(contract_id)
    scope(ctx, contract["client_id"])
    return respond(domain.serialize(contract))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(
        db.contracts.values(), ctx, domain.serialize,
        owner_fn=lambda c: c["client_id"],
        filters=(("client_id", "client_id"), ("status", "status"),
                 ("harvest_year", "harvest_year")))


@bp.route("/contracts/<contract_id>/transitions", methods=["POST"])
def contract_transitions(contract_id):
    ctx = guard([FACILITY_ADMIN], CONTRACT_ACTIONS)
    action = v_enum(ctx.body, "action", set(CONTRACT_ACTIONS))
    contract = domain.get_contract(contract_id)
    client = db.clients.get(contract["client_id"])

    if action == "SUBMIT":
        declared(contract["status"] == "DRAFT")
        # Rung 65 -- interval sanity.
        if not (contract["_eff_to_dt"] > contract["_eff_from_dt"]):
            raise ApiError(ERR_INVALID_INTERVAL,
                           "effective_to must be strictly after effective_from.")
        contract["status"] = "PENDING_SIGNATURE"
    elif action == "REVISE":
        declared(contract["status"] == "PENDING_SIGNATURE")
        contract["status"] = "DRAFT"
    elif action == "ACTIVATE":
        declared(contract["status"] == "PENDING_SIGNATURE")
        _require_client_active(client)
        contract["status"] = "ACTIVE"
    elif action == "REINSTATE":
        declared(contract["status"] == "SUSPENDED")
        _require_client_active(client)
        contract["status"] = "ACTIVE"
    elif action == "SUSPEND":
        declared(contract["status"] == "ACTIVE")
        contract["status"] = "SUSPENDED"
        touch(contract)
        cancelled = False
        for allocation in domain.contract_allocations(contract["id"]):
            if allocation["status"] == "RESERVED":
                allocation["status"] = "CANCELLED"
                touch(allocation)
                cancelled = True
        if cancelled:
            domain.recompute_contract_counters_and_touch(contract)
        return respond(domain.serialize(contract))
    else:  # TERMINATE
        declared(contract["status"] in ("ACTIVE", "SUSPENDED"))
        # Rung 85 -- terminal safety gate.
        for allocation in domain.contract_allocations(contract["id"]):
            if allocation["status"] in domain.LIVE_ALLOCATION_STATUSES:
                raise ApiError(ERR_ALLOCATIONS_OUTSTANDING,
                               "The contract still owns a live allocation.")
        contract["status"] = "TERMINATED"

    touch(contract)
    return respond(domain.serialize(contract))


def _require_client_active(client):
    if client is None or client["status"] != "ACTIVE":
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, "The owning client is not ACTIVE.")


@bp.route("/contracts/<contract_id>/storage-accrual", methods=["GET"])
def storage_accrual_projection(contract_id):
    ctx = guard([FACILITY_ADMIN, COMPLIANCE_OFFICER, CLIENT_REP], read_body=False)
    raw_through = request.args.get("through_at")
    if raw_through is None or raw_through == "":
        raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'through_at' is required.")
    try:
        through_dt = parse_iso(raw_through)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST,
                       "Query parameter 'through_at' must be an ISO 8601 datetime.")
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "OCCUPANCY"
    if variant not in STORAGE_VARIANTS:
        raise ApiError(ERR_INVALID_REQUEST,
                       "Query parameter 'variant' must be OCCUPANCY or "
                       "VESSEL_FOOTPRINT.")

    contract = domain.get_contract(contract_id)
    scope(ctx, contract["client_id"])
    subject_count, charge_cents = domain.storage_projection(
        contract, through_dt, variant)
    return respond({
        "contract_id": contract["id"],
        "variant": variant,
        "through_at": iso(through_dt),
        "subject_count": subject_count,
        "charge_cents": charge_cents,
    })


@bp.route("/contracts/<contract_id>/storage-accruals", methods=["POST"])
def storage_accrual_post(contract_id):
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    through_raw, through_dt = v_datetime(body, "through_at")
    expected = v_int(body, "expected_contract_version")

    contract = domain.get_contract(contract_id)

    # Rung 35 -- stale-parent rejection on the shared ledger.
    if expected != contract["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION,
                       "The contract has moved since it was last read.")

    # Posting always uses the OCCUPANCY reading.
    _count, charge_cents = domain.storage_projection(contract, through_dt, "OCCUPANCY")
    contract["billed_total_cents"] = contract["billed_total_cents"] + charge_cents
    contract["storage_billed_through"] = through_raw
    contract["_billed_through_dt"] = through_dt
    touch(contract)
    return respond(domain.serialize(contract))
