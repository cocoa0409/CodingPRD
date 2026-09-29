"""Vessel cycles: scheduling, booking, running, CCP capture, disposition.

PRD 3.5, 3.6 and 3.8.
"""
from datetime import timedelta

from flask import Blueprint

import calc
import clock
import errors
import response
import serializers
import services
import validation
from db import db, insert, insert_event, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OPERATOR, ROLE_QUALITY,
                        ROLE_SCHEDULER, acting_user, endpoint)

bp = Blueprint("cycles", __name__)

CYCLE_STATES = ("SCHEDULED", "LOADED", "RUNNING", "COMPLETED_CLEAN",
                "COMPLETED_DEVIATED", "DISPOSITIONED", "ABORTED", "CANCELLED")
HOLD_REASON_CCP = "CCP deviation"


# ------------------------------------------------------------------ scheduling
@bp.post("/vessel-cycles")
@endpoint([ROLE_SCHEDULER])
def schedule_cycle():
    data = validation.body()
    vessel_id = validation.get_id(data, "vessel_id")
    product_family_id = validation.get_id(data, "product_family_id")
    scheduled_start = validation.get_datetime(data, "scheduled_start")
    target_pressure_mpa = validation.get_num(data, "target_pressure_mpa",
                                             exclusive_minimum=0)
    target_hold_seconds = validation.get_int(data, "target_hold_seconds",
                                             exclusive_minimum=0)

    family = services.find(db.product_families, product_family_id,
                           "ERR_PRODUCT_FAMILY_NOT_FOUND")
    vessel = services.find(db.vessels, vessel_id, "ERR_VESSEL_NOT_FOUND")

    if calc.D(target_pressure_mpa) > calc.D(vessel["max_pressure_mpa"]):
        raise errors.unprocessable("ERR_PRESSURE_ABOVE_VESSEL_MAX",
                                   "The target pressure exceeds the vessel's "
                                   "mechanical ceiling.")

    seconds = calc.cycle_seconds(
        calc.estimated_come_up_seconds(target_pressure_mpa,
                                       vessel["pump_ramp_rate_mpa_per_sec"]),
        target_hold_seconds, vessel["decompression_seconds"])
    scheduled_end = scheduled_start + timedelta(seconds=seconds)
    utilization = calc.utilization_pct(0, vessel["basket_count"])
    fee = calc.tolling_fee_cents(seconds, utilization)

    occupants = [row for row in db.cycles.values()
                 if row["vessel_id"] == vessel_id
                 and row["state"] in services.OCCUPYING_CYCLE_STATES]

    for occupant in ordered(occupants):
        if (scheduled_start < occupant["scheduled_end"]
                and occupant["scheduled_start"] < scheduled_end):
            raise errors.conflict("ERR_VESSEL_WINDOW_CONFLICT",
                                  "The vessel is already occupied in that window.")

    predecessor = None
    successor = None
    for occupant in occupants:
        if occupant["scheduled_end"] <= scheduled_start:
            if (predecessor is None
                    or occupant["scheduled_end"] > predecessor["scheduled_end"]):
                predecessor = occupant
        if occupant["scheduled_start"] >= scheduled_end:
            if (successor is None
                    or occupant["scheduled_start"] < successor["scheduled_start"]):
                successor = occupant

    for neighbour, gap in ((predecessor,
                            None if predecessor is None
                            else (scheduled_start
                                  - predecessor["scheduled_end"]).total_seconds()),
                           (successor,
                            None if successor is None
                            else (successor["scheduled_start"]
                                  - scheduled_end).total_seconds())):
        if neighbour is None:
            continue
        neighbour_family = services.family_of_cycle(neighbour)
        if (neighbour_family["cross_contamination_group"]
                == family["cross_contamination_group"]):
            continue
        required = max(int(neighbour_family["cleanout_minutes"]),
                       int(family["cleanout_minutes"])) * 60
        if int(gap) < required:
            raise errors.conflict("ERR_CLEANOUT_GAP_REQUIRED",
                                  "A sanitation gap is required between cycles of "
                                  "different segregation groups.")

    row = insert(db.cycles, {
        "vessel_id": vessel_id,
        "product_family_id": product_family_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "target_pressure_mpa": target_pressure_mpa,
        "target_hold_seconds": target_hold_seconds,
        "baskets_used_total": 0,
        "utilization_pct": utilization,
        "estimated_cycle_seconds": seconds,
        "estimated_tolling_fee_cents": fee,
        "actual_cycle_seconds": None,
        "actual_tolling_fee_cents": None,
        "state": "SCHEDULED",
        "started_at": None,
        "dispositioned_at": None,
    })
    return response.created(serializers.plain(row))


# --------------------------------------------------------------- booking loads
@bp.post("/vessel-cycles/<row_id>/loads")
@endpoint([ROLE_SCHEDULER])
def create_load(row_id):
    data = validation.body()
    lot_id = validation.get_id(data, "lot_id")
    contract_id = validation.get_id(data, "contract_id")
    baskets_used = validation.get_int(data, "baskets_used", exclusive_minimum=0)
    units_loaded = validation.get_int(data, "units_loaded", exclusive_minimum=0)
    expected_cycle_version = validation.get_int(data, "expected_cycle_version")

    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    lot = services.find(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    contract = services.find(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")

    if expected_cycle_version != cycle["version"]:
        raise errors.precondition("ERR_STALE_CYCLE_VERSION",
                                  "The cycle has changed since it was read.")

    if lot["custody_state"] != "IN_COLD_STORAGE":
        raise errors.conflict("ERR_INVALID_LOT_CUSTODY_STATE",
                              "Only a pallet in cold storage may be booked onto a "
                              "cycle.")
    if cycle["state"] not in ("SCHEDULED", "LOADED"):
        raise errors.conflict("ERR_INVALID_CYCLE_STATE",
                              "Loads may only be booked onto a SCHEDULED or LOADED "
                              "cycle.")
    if contract["status"] in ("DRAFT", "CLOSED"):
        raise errors.conflict("ERR_INVALID_CONTRACT_STATE",
                              "A DRAFT or CLOSED contract cannot back a load.")

    live = services.live_loads(cycle["id"])
    if any(row["lot_id"] == lot_id for row in live):
        raise errors.conflict("ERR_DUPLICATE_CYCLE_LOAD",
                              "That pallet is already booked onto this cycle.")

    qualification = services.qualification_of(lot)
    if qualification["status"] != "QUALIFIED":
        raise errors.unprocessable("ERR_QUALIFICATION_NOT_QUALIFIED",
                                   "The pallet's process recipe is not qualified.")
    if not (qualification["expires_at"] is not None
            and qualification["expires_at"] > clock.now()):
        raise errors.unprocessable("ERR_QUALIFICATION_EXPIRED",
                                   "The pallet's qualification has expired.")
    if qualification["product_family_id"] != cycle["product_family_id"]:
        raise errors.unprocessable("ERR_FAMILY_MISMATCH",
                                   "A cycle runs a single product family only.")

    family = services.family_of_cycle(cycle)
    if family["requires_dedicated_cycle"]:
        for row in live:
            other = services.lot_of(row)
            if other is not None and other["customer_id"] != lot["customer_id"]:
                raise errors.unprocessable("ERR_DEDICATED_CYCLE_REQUIRED",
                                           "This family requires a dedicated cycle per "
                                           "customer.")

    vessel = services.vessel_of(cycle)
    baskets_total = sum(row["baskets_used"] for row in live)
    if baskets_total + baskets_used > vessel["basket_count"]:
        raise errors.unprocessable("ERR_BASKET_CAPACITY_EXCEEDED",
                                   "The chamber cannot hold that many baskets.")
    if units_loaded > lot["units_untreated"]:
        raise errors.unprocessable("ERR_INSUFFICIENT_UNTREATED_UNITS",
                                   "The pallet does not hold that many untreated "
                                   "units.")

    if not (contract["window_start"] <= cycle["scheduled_start"]
            <= contract["window_end"]):
        raise errors.unprocessable("ERR_CONTRACT_WINDOW_MISMATCH",
                                   "The cycle falls outside the contract window.")
    if contract["customer_id"] != lot["customer_id"]:
        raise errors.not_owner("The contract belongs to a different customer than the "
                              "pallet.")

    if services.contract_ledger(contract)["available_slots"] < 1:
        raise errors.conflict("ERR_CONTRACT_CAPACITY_EXHAUSTED",
                              "The contract has no available slots left.")

    load = insert(db.loads, {
        "cycle_id": cycle["id"],
        "lot_id": lot_id,
        "contract_id": contract_id,
        "baskets_used": baskets_used,
        "units_loaded": units_loaded,
        "allocated_fee_cents": None,
        "units_inspected": None,
        "leaker_units": None,
        "leaker_ppm": None,
        "chargeback_party": None,
        "chargeback_cents": 0,
        "inspection_state": "PENDING_INSPECTION",
        "disposition_state": "PENDING",
    })

    if cycle["state"] == "SCHEDULED":
        cycle["state"] = "LOADED"
    services.recompute_cycle_estimate(cycle)
    touch(cycle)
    services.recompute_contract(contract)

    return response.created(serializers.plain(load))


# ------------------------------------------------------------------- the run
@bp.post("/vessel-cycles/<row_id>/start")
@endpoint([ROLE_OPERATOR])
def start_cycle(row_id):
    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    if cycle["state"] not in ("SCHEDULED", "LOADED"):
        raise errors.conflict("ERR_INVALID_CYCLE_STATE",
                              "Only a SCHEDULED or LOADED cycle may be pressurised.")

    loads = services.pending_loads(cycle["id"])
    required_pressure, required_hold, _ = services.chamber_requirements(loads)
    if required_pressure is not None:
        if calc.D(cycle["target_pressure_mpa"]) < required_pressure:
            raise errors.unprocessable("ERR_CYCLE_TARGET_BELOW_QUALIFIED",
                                       "The chamber target is below a loaded pallet's "
                                       "qualified pressure.")
    if required_hold is not None and int(cycle["target_hold_seconds"]) < required_hold:
        raise errors.unprocessable("ERR_CYCLE_TARGET_BELOW_QUALIFIED",
                                   "The chamber target is below a loaded pallet's "
                                   "qualified hold time.")

    vessel = services.vessel_of(cycle)
    if vessel["status"] != "AVAILABLE":
        raise errors.unprocessable("ERR_VESSEL_NOT_AVAILABLE",
                                   "The vessel is not available.")

    if not loads:
        raise errors.unprocessable("ERR_EMPTY_CYCLE",
                                   "An empty chamber is never pressurised.")

    for load in loads:
        lot = services.lot_of(load)
        if lot is None or lot["custody_state"] != "IN_COLD_STORAGE":
            raise errors.conflict("ERR_INVALID_LOT_CUSTODY_STATE",
                                  "A loaded pallet is no longer in cold storage.")

    cycle["state"] = "RUNNING"
    cycle["started_at"] = clock.now()
    touch(cycle)

    vessel["status"] = "IN_USE"
    touch(vessel)

    for load in loads:
        lot = services.lot_of(load)
        lot["custody_state"] = "IN_VESSEL"
        services.move_units(lot, "units_untreated", "units_in_vessel",
                            load["units_loaded"])
        touch(lot)

    return response.object_response(serializers.plain(cycle))


@bp.post("/vessel-cycles/<row_id>/cycle-logs")
@endpoint([ROLE_OPERATOR])
def create_cycle_log(row_id):
    data = validation.body()
    actual_pressure_mpa = validation.get_num(data, "actual_pressure_mpa")
    actual_hold_seconds = validation.get_int(data, "actual_hold_seconds",
                                             exclusive_minimum=0)
    come_up_seconds = validation.get_int(data, "come_up_seconds", exclusive_minimum=0)
    water_temp_c = validation.get_num(data, "water_temp_c")

    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    if cycle["state"] != "RUNNING":
        raise errors.conflict("ERR_INVALID_CYCLE_STATE",
                              "The CCP record may only be captured on a RUNNING "
                              "cycle.")
    if services.log_of_cycle(cycle["id"]) is not None:
        raise errors.conflict("ERR_DUPLICATE_CYCLE_LOG",
                              "This cycle already has its control-point record.")

    vessel = services.vessel_of(cycle)
    loads = services.pending_loads(cycle["id"])
    required_pressure, required_hold, water_limit = services.chamber_requirements(loads)
    verdict = calc.ccp_evaluation(actual_pressure_mpa, actual_hold_seconds,
                                  water_temp_c, required_pressure, required_hold,
                                  water_limit)

    seconds = calc.cycle_seconds(come_up_seconds, actual_hold_seconds,
                                 vessel["decompression_seconds"])

    log = insert_event(db.cycle_logs, {
        "cycle_id": cycle["id"],
        "actual_pressure_mpa": actual_pressure_mpa,
        "actual_hold_seconds": actual_hold_seconds,
        "come_up_seconds": come_up_seconds,
        "water_temp_c": water_temp_c,
        "actual_cycle_seconds": seconds,
        "ccp_verdict": verdict["ccp_verdict"],
        "deviation_flags": list(verdict["flags"]),
        "logged_by_user_id": acting_user(),
        "logged_at": clock.now(),
    })

    deviated = verdict["ccp_verdict"] == "DEVIATION"
    cycle["actual_cycle_seconds"] = seconds
    cycle["state"] = "COMPLETED_DEVIATED" if deviated else "COMPLETED_CLEAN"
    touch(cycle)

    vessel["status"] = "AVAILABLE"
    vessel["cycles_run_count"] += 1
    touch(vessel)

    for load in loads:
        lot = services.lot_of(load)
        if lot is None:
            continue
        lot["custody_state"] = "TREATED"
        services.move_units(lot, "units_in_vessel", "units_treated",
                            load["units_loaded"])
        if deviated and lot["release_state"] == "NOT_RELEASED":
            lot["release_state"] = "ON_HOLD_FOR_TEST"
            lot["hold_reason"] = HOLD_REASON_CCP
        touch(lot)

    if deviated:
        insert(db.deviations, {
            "cycle_id": cycle["id"],
            "cycle_log_id": log["id"],
            "cycle_load_id": None,
            "deviation_type": verdict["flags"][0],
            "severity": verdict["severity"],
            "worst_shortfall_pct": verdict["worst_shortfall_pct"],
            "status": "OPEN",
            "root_cause_code": None,
            "chargeback_party": None,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
        })

    return response.created(serializers.plain(log))


@bp.get("/vessel-cycles/<row_id>/cycle-logs")
@endpoint([ROLE_OPERATOR, ROLE_QUALITY, ROLE_ADMIN])
def list_cycle_logs(row_id):
    limit, offset = validation.pagination()
    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    rows = services.logs_of_cycle(cycle["id"])
    return response.page(rows, serializers.plain, limit, offset)


@bp.post("/vessel-cycles/<row_id>/terminate")
@endpoint([ROLE_SCHEDULER, ROLE_OPERATOR])
def terminate_cycle(row_id):
    data = validation.body()
    validation.get_str(data, "reason")

    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    if cycle["state"] not in ("SCHEDULED", "LOADED", "RUNNING"):
        raise errors.conflict("ERR_INVALID_CYCLE_STATE",
                              "Only a SCHEDULED, LOADED or RUNNING cycle may be "
                              "terminated.")

    running = cycle["state"] == "RUNNING"
    loads = services.pending_loads(cycle["id"])

    cycle["state"] = "ABORTED" if running else "CANCELLED"
    touch(cycle)

    for load in loads:
        load["disposition_state"] = "VOIDED"
        touch(load)
        if running:
            lot = services.lot_of(load)
            if lot is None:
                continue
            lot["custody_state"] = "IN_COLD_STORAGE"
            services.move_units(lot, "units_in_vessel", "units_untreated",
                                load["units_loaded"])
            touch(lot)

    if running:
        vessel = services.vessel_of(cycle)
        vessel["status"] = "AVAILABLE"
        touch(vessel)

    services.recompute_contracts_of(loads)
    return response.object_response(serializers.plain(cycle))


@bp.post("/vessel-cycles/<row_id>/disposition")
@endpoint([ROLE_QUALITY])
def disposition_cycle(row_id):
    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    if cycle["state"] not in ("COMPLETED_CLEAN", "COMPLETED_DEVIATED"):
        raise errors.conflict("ERR_INVALID_CYCLE_STATE",
                              "Only a completed cycle may be dispositioned.")

    deviations = services.deviations_of_cycle(cycle["id"])
    if cycle["state"] == "COMPLETED_CLEAN":
        if any(row["status"] == "OPEN" for row in deviations):
            raise errors.conflict("ERR_DEVIATION_UNRESOLVED",
                                  "A deviation on this cycle is still open.")
    else:
        if any(row["status"] != "ADJUDICATED_ACCEPT" for row in deviations):
            raise errors.conflict("ERR_DEVIATION_UNRESOLVED",
                                  "Every deviation on a deviated cycle must be "
                                  "adjudicated as accepted before disposition.")

    complete_disposition(cycle)
    return response.object_response(serializers.plain(cycle))


def complete_disposition(cycle, reprocessed=False):
    """Freeze the ACTUAL fee, allocate it and move the loads (PRD 3.8 / 3.7)."""
    log = services.log_of_cycle(cycle["id"])
    participants = services.pending_loads(cycle["id"])

    fee = services.actual_fee_cents(cycle, log) if log is not None else 0
    allocation = services.allocate_fee_to_loads(cycle, fee, participants)

    for load in participants:
        load["allocated_fee_cents"] = allocation.get(load["id"], 0)
        load["disposition_state"] = "REPROCESSED" if reprocessed else "ALLOCATED"
        touch(load)

    cycle["actual_tolling_fee_cents"] = fee
    cycle["state"] = "DISPOSITIONED"
    cycle["dispositioned_at"] = clock.now()
    touch(cycle)
    services.recompute_contracts_of(participants)
    return participants


@bp.get("/vessel-cycles/<row_id>")
@endpoint([ROLE_SCHEDULER, ROLE_OPERATOR, ROLE_QUALITY, ROLE_ADMIN, ROLE_CUSTOMER])
def get_cycle(row_id):
    cycle = services.find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")
    return response.object_response(serializers.plain(cycle))


@bp.get("/vessel-cycles")
@endpoint([ROLE_SCHEDULER, ROLE_OPERATOR, ROLE_QUALITY, ROLE_ADMIN])
def list_cycles():
    limit, offset = validation.pagination()
    vessel_id = validation.qs_str("vessel_id")
    product_family_id = validation.qs_str("product_family_id")
    state = validation.qs_enum("state", CYCLE_STATES)
    scheduled_from = validation.qs_datetime("scheduled_from")
    scheduled_to = validation.qs_datetime("scheduled_to")

    rows = []
    for row in db.cycles.values():
        if vessel_id is not None and row["vessel_id"] != vessel_id:
            continue
        if product_family_id is not None and row["product_family_id"] != product_family_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if scheduled_from is not None and row["scheduled_start"] < scheduled_from:
            continue
        if scheduled_to is not None and row["scheduled_start"] > scheduled_to:
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)
