"""Voyage scheduling, discharge lifecycle and yard intake (PRD §3.1)."""
from datetime import timedelta

from flask import Blueprint

import db
import validation as v
from errors import fail, invalid, invalid_state
from middleware import OPS_ROLES, ROLE_PLANNER, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("vessels", __name__)

BERTH_OCCUPYING_STATUSES = ("SCHEDULED", "DISCHARGING")


@bp.route("/vpc/vessels", methods=["POST"])
def create_vessel():
    authenticate([ROLE_PLANNER])
    body = v.body()

    # Band 4: body foreign keys, left to right.
    center = None
    if v.present(body, "processing_center_id"):
        center = db.centers.get(body["processing_center_id"])
        if center is None:
            fail("ERR_REFERENCE_NOT_FOUND", "processing_center_id does not resolve")
    berth = None
    if v.present(body, "berth_id"):
        berth = db.berths.get(body["berth_id"])
        if berth is None:
            fail("ERR_REFERENCE_NOT_FOUND", "berth_id does not resolve")

    v.req_str(body, "processing_center_id")
    v.req_str(body, "berth_id")
    voyage_code = v.req_str(body, "voyage_code")
    carrier_scac = v.req_str(body, "carrier_scac")
    window_start, window_end = v.req_interval(body, "berth_window_start", "berth_window_end")
    declared = v.req_int(body, "declared_unit_count", minimum=1)

    if any(
        s["processing_center_id"] == center["id"] and s["voyage_code"] == voyage_code
        for s in db.vessels.values()
    ):
        fail("ERR_DUPLICATE_KEY", "voyage_code %s already exists at this center" % voyage_code)

    # Berth window exclusivity plus the turnaround buffer on both sides.
    buffer_delta = timedelta(minutes=berth["turnaround_buffer_minutes"])
    for peer in db.vessels.values():
        if peer["berth_id"] != berth["id"]:
            continue
        if peer["discharge_status"] not in BERTH_OCCUPYING_STATUSES:
            continue
        if (
            window_start < peer["berth_window_end"] + buffer_delta
            and peer["berth_window_start"] < window_end + buffer_delta
        ):
            fail(
                "ERR_BERTH_WINDOW_CONFLICT",
                "the requested berth window does not clear voyage %s by the turnaround buffer"
                % peer["voyage_code"],
            )

    record = db.base_record()
    record.update(
        {
            "processing_center_id": center["id"],
            "berth_id": berth["id"],
            "voyage_code": voyage_code,
            "carrier_scac": carrier_scac,
            "berth_window_start": window_start,
            "berth_window_end": window_end,
            "declared_unit_count": declared,
            "discharged_unit_count": 0,
            "discharge_status": "SCHEDULED",
        }
    )
    db.vessels[record["id"]] = record
    return object_response(ser.vessel(record), 201)


@bp.route("/vpc/vessels/<vessel_id>", methods=["GET"])
def read_vessel(vessel_id):
    authenticate(OPS_ROLES)
    vessel = db.must_get("vessels", vessel_id)
    state.recompute_vessel(vessel)
    return object_response(ser.vessel(vessel))


@bp.route("/vpc/vessels", methods=["GET"])
def list_vessels():
    authenticate(OPS_ROLES)
    center_id = v.query_filter("processing_center_id")
    berth_id = v.query_filter("berth_id")
    status = v.query_filter("discharge_status")
    voyage_code = v.query_filter("voyage_code")
    records = db.ordered(db.vessels)
    for vessel in records:
        state.recompute_vessel(vessel)
    if center_id is not None:
        records = [s for s in records if s["processing_center_id"] == center_id]
    if berth_id is not None:
        records = [s for s in records if s["berth_id"] == berth_id]
    if status is not None:
        records = [s for s in records if s["discharge_status"] == status]
    if voyage_code is not None:
        records = [s for s in records if s["voyage_code"] == voyage_code]
    items, limit, offset, total = v.paginate(records, ser.vessel)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/vessels/<vessel_id>/start-discharge", methods=["POST"])
def start_discharge(vessel_id):
    authenticate([ROLE_PLANNER])
    vessel = db.must_get("vessels", vessel_id)
    if vessel["discharge_status"] != "SCHEDULED":
        invalid_state("discharge can only be started from SCHEDULED")
    if db.clock_now() < vessel["berth_window_start"]:
        fail("ERR_BERTH_WINDOW_NOT_OPEN", "the reserved berth window has not opened yet")
    vessel["discharge_status"] = "DISCHARGING"
    db.touch(vessel)
    return object_response(ser.vessel(vessel))


@bp.route("/vpc/vessels/<vessel_id>/complete-discharge", methods=["POST"])
def complete_discharge(vessel_id):
    authenticate([ROLE_PLANNER])
    vessel = db.must_get("vessels", vessel_id)
    if vessel["discharge_status"] != "DISCHARGING":
        invalid_state("discharge can only be completed from DISCHARGING")
    state.recompute_vessel(vessel)
    if vessel["discharged_unit_count"] < 1:
        fail("ERR_NO_UNITS_DISCHARGED", "no unit has been discharged off this voyage")
    vessel["discharge_status"] = "DISCHARGE_COMPLETE"
    db.touch(vessel)
    return object_response(ser.vessel(vessel))


@bp.route("/vpc/vessels/<vessel_id>/vehicles", methods=["POST"])
def discharge_vehicle(vessel_id):
    authenticate([ROLE_PLANNER])
    vessel = db.must_get("vessels", vessel_id)
    body = v.body()
    vin = v.req_str(body, "vin")
    if len(vin) != 17:
        invalid("vin must be exactly 17 characters")
    model_line = v.req_enum(body, "model_line", calc.MODEL_LINES)
    pio_program_code = v.opt_str(body, "pio_program_code")

    if any(veh["vin"] == vin for veh in db.vehicles.values()):
        fail("ERR_DUPLICATE_KEY", "vin %s already exists" % vin)

    if vessel["discharge_status"] != "DISCHARGING":
        invalid_state("units may only be discharged while the voyage is DISCHARGING")

    center = db.centers.get(vessel["processing_center_id"])
    if center is not None:
        state.recompute_center(center)
        if center["yard_posture"] == "GRIDLOCK":
            fail("ERR_YARD_GRIDLOCK", "the destination yard is in GRIDLOCK")

    record = db.base_record()
    record.update(
        {
            "processing_center_id": vessel["processing_center_id"],
            "vessel_id": vessel["id"],
            "vin": vin,
            "model_line": model_line,
            "pio_program_code": pio_program_code,
            "yard_presence": "IN_YARD",
            "yard_in_at": db.clock_now(),
            "gate_out_at": None,
            "processing_status": "DISCHARGED",
            "damage_status": "NONE",
            "damage_opened_at": None,
            "damage_cleared_at": None,
            "severity_index": 0,
            "claim_mandatory": False,
            "stop_ship_blocked": False,
            "blocking_hold_order_id": None,
            "rework_cycle_count": 0,
            "blocked_credit_days": 0,
            "storage_charge_provisional_cents": 0,
            "storage_charge_final_cents": 0,
            "accessory_billed_cents": 0,
        }
    )

    # A live model-line campaign catches units that had not yet arrived.
    for hold in db.ordered(db.hold_orders):
        if (
            hold["status"] == "OPEN"
            and hold["scope_type"] == "MODEL_LINE"
            and hold["processing_center_id"] == record["processing_center_id"]
            and hold["model_line"] == model_line
        ):
            record["stop_ship_blocked"] = True
            record["blocking_hold_order_id"] = hold["id"]
            break

    db.vehicles[record["id"]] = record
    state.recompute_vessel(vessel)
    if center is not None:
        state.recompute_center(center)
    return object_response(ser.vehicle(record), 201)
