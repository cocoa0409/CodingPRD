"""Vessel allocations: reserving windows, committing wine, release and cancel."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import domain
from auth import ALL_ROLES, CELLAR_SUPERVISOR, FACILITY_ADMIN, guard, scope
from calc import CLEANING_BUFFER_HOURS
from envelope import respond
from errors import (
    ApiError,
    ERR_BARREL_SLOTS_EXHAUSTED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CROSS_CONTRACT_REFERENCE,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_STATE,
    ERR_OUTSIDE_CONTRACT_WINDOW,
    ERR_STALE_VESSEL_VERSION,
    ERR_TANK_ENTITLEMENT_EXCEEDED,
    ERR_VESSEL_CAPACITY_EXCEEDED,
    ERR_VESSEL_NOT_CLEAN,
    ERR_VESSEL_OVERLAP,
)
from helpers import declared, run_list
from store import db, iso, new_entity, touch
from validation import v_datetime, v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("allocations", __name__)

ALLOCATION_ACTIONS = {
    "RELEASE": [CELLAR_SUPERVISOR],
    "CANCEL": [FACILITY_ADMIN],
}


@bp.route("/vessel-allocations", methods=["POST"])
def create_allocation():
    ctx = guard([FACILITY_ADMIN, CELLAR_SUPERVISOR])
    body = ctx.body
    contract_id = v_string(body, "contract_id")
    vessel_id = v_string(body, "vessel_id")
    start_raw, start_dt = v_datetime(body, "start_at")
    end_raw, end_dt = v_datetime(body, "end_at")
    allocated = v_number(body, "allocated_gallons", gt=0)
    expected_version = v_int(body, "expected_vessel_version")

    # Rung 15 -- body foreign keys.
    contract = domain.get_contract(contract_id)
    vessel = domain.get_vessel(vessel_id)

    # Rung 35 -- stale-parent rejection on the vessel's booking calendar.
    if expected_version != vessel["version"]:
        raise ApiError(ERR_STALE_VESSEL_VERSION,
                       "The vessel has moved since it was last read.")

    # Rung 40 -- cross-entity state gate.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "The governing contract is not ACTIVE.")

    # Rung 65 -- interval sanity and window containment.
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_INTERVAL,
                       "end_at must be strictly after start_at.")
    if start_dt < contract["_eff_from_dt"] or end_dt > contract["_eff_to_dt"]:
        raise ApiError(ERR_OUTSIDE_CONTRACT_WINDOW,
                       "The occupancy interval falls outside the contract window.")

    # Rung 70 -- exclusive vessel occupancy with a trailing cleaning buffer.
    buffer = timedelta(hours=CLEANING_BUFFER_HOURS)
    for other in db.allocations.values():
        if other["vessel_id"] != vessel["id"]:
            continue
        if other["status"] not in domain.LIVE_ALLOCATION_STATUSES:
            continue
        if start_dt < other["_end_dt"] + buffer and other["_start_dt"] < end_dt:
            raise ApiError(ERR_VESSEL_OVERLAP,
                           "The requested window intersects a live occupancy.")

    # Rung 75 -- capacity and entitlement ceilings.
    if allocated > D(vessel["capacity_gallons"]):
        raise ApiError(ERR_VESSEL_CAPACITY_EXCEEDED,
                       "allocated_gallons exceeds the vessel's working capacity.")
    if vessel["vessel_type"] == "TANK":
        if D(contract["gallons_allocated"]) + allocated > D(
                contract["tank_gallons_entitled"]):
            raise ApiError(ERR_TANK_ENTITLEMENT_EXCEEDED,
                           "The contract's tank entitlement would be exceeded.")
    else:
        if contract["barrel_slots_used"] + 1 > contract["barrel_slots_entitled"]:
            raise ApiError(ERR_BARREL_SLOTS_EXHAUSTED,
                           "The contract's barrel slots are exhausted.")

    allocation = new_entity({
        "contract_id": contract_id,
        "vessel_id": vessel_id,
        "lot_id": None,
        "start_at": start_raw,
        "end_at": end_raw,
        "allocated_gallons": allocated,
        "status": "RESERVED",
        "committed_at": None,
        "released_at": None,
        "occupied_days": 0,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_committed_dt": None,
        "_released_dt": None,
    })
    db.allocations[allocation["id"]] = allocation

    domain.recompute_contract_counters_and_touch(contract)
    touch(vessel)
    return respond(domain.serialize(allocation), 201)


@bp.route("/vessel-allocations/<allocation_id>", methods=["GET"])
def read_allocation(allocation_id):
    ctx = guard(ALL_ROLES, read_body=False)
    allocation = domain.get_allocation(allocation_id)
    scope(ctx, domain.allocation_client_id(allocation))
    return respond(domain.serialize(allocation))


@bp.route("/vessel-allocations", methods=["GET"])
def list_allocations():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.allocations.values(), ctx, domain.serialize,
                    owner_fn=domain.allocation_client_id,
                    filters=(("contract_id", "contract_id"),
                             ("vessel_id", "vessel_id"),
                             ("lot_id", "lot_id"),
                             ("status", "status")))


@bp.route("/vessel-allocations/<allocation_id>/commit", methods=["POST"])
def commit_allocation(allocation_id):
    ctx = guard([CELLAR_SUPERVISOR])
    lot_id = v_string(ctx.body, "lot_id")

    allocation = domain.get_allocation(allocation_id)
    lot = domain.get_lot(lot_id)

    # Rung 30 -- declared transition.
    declared(allocation["status"] == "RESERVED")

    # Rung 40 -- cross-entity state gates.
    contract = db.contracts.get(allocation["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "The governing contract is not ACTIVE.")
    vessel = db.vessels.get(allocation["vessel_id"])
    if vessel is None or vessel["condition"] != "CLEAN":
        raise ApiError(ERR_VESSEL_NOT_CLEAN, "The vessel is not CLEAN.")

    # Rung 60 -- cross-aggregate ownership.
    if lot["contract_id"] != allocation["contract_id"]:
        raise ApiError(ERR_CROSS_CONTRACT_REFERENCE,
                       "The lot belongs to a different contract.")

    # The lot must not already be housed.
    if lot["current_vessel_id"] is not None:
        raise ApiError(ERR_INVALID_STATE, "The lot is already housed in a vessel.")

    # Rung 75 -- the second reading of the capacity ceiling.
    if D(lot["volume_gallons"]) > D(allocation["allocated_gallons"]):
        raise ApiError(ERR_VESSEL_CAPACITY_EXCEEDED,
                       "The lot's volume exceeds the allocation's held capacity.")

    now = db.now()
    allocation["status"] = "COMMITTED"
    allocation["lot_id"] = lot["id"]
    allocation["committed_at"] = iso(now)
    allocation["_committed_dt"] = now
    touch(allocation)

    lot["current_vessel_id"] = allocation["vessel_id"]
    touch(lot)
    return respond(domain.serialize(allocation))


@bp.route("/vessel-allocations/<allocation_id>/transitions", methods=["POST"])
def allocation_transitions(allocation_id):
    ctx = guard([FACILITY_ADMIN, CELLAR_SUPERVISOR], ALLOCATION_ACTIONS)
    action = v_enum(ctx.body, "action", set(ALLOCATION_ACTIONS))
    allocation = domain.get_allocation(allocation_id)

    if action == "CANCEL":
        declared(allocation["status"] == "RESERVED")
        # Branch A -- the vessel is left entirely untouched.
        allocation["status"] = "CANCELLED"
        touch(allocation)
        contract = db.contracts.get(allocation["contract_id"])
        if contract is not None:
            domain.recompute_contract_counters_and_touch(contract)
    else:  # RELEASE
        declared(allocation["status"] == "COMMITTED")
        # Branch B -- dirties the vessel and unhouses the lot.
        domain.release_allocation(allocation, clear_lot_housing=True)

    return respond(domain.serialize(allocation))
