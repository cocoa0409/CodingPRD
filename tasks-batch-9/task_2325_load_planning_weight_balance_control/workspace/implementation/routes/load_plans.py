"""Load plans: opening, computing, offloading and gate-bag absorption (PRD §3.3, §3.6)."""
from flask import Blueprint

import calc
import db
import resolve
import response
import validate
from calc import D
from errors import (
    ERR_CG_OUT_OF_ENVELOPE,
    ERR_COMPARTMENT_KIND_MISMATCH,
    ERR_COMPARTMENT_NOT_ON_AIRCRAFT,
    ERR_DUPLICATE_KEY,
    ERR_FLIGHT_INVALID_STATE,
    ERR_OFFLOAD_INSUFFICIENT,
    ERR_PLAN_INVALID_STATE,
    ERR_STALE_FLIGHT_VERSION,
    fail,
)
from middleware import ANY_ROLE, authorize
from services import balance

bp = Blueprint("load_plans", __name__)

GATE_BAG_POLICIES = ("ABSORB_INTO_UNDERLOAD", "DEFER_ALL")
OFFLOAD_STRATEGIES = ("PRIORITY_FIRST", "FEWEST_PIECES")
ROUNDING_MODES = ("PER_LINE_THEN_SUM", "SUM_THEN_ROUND")

PLAN_ZERO_FIELDS = (
    "base_payload_kg",
    "frozen_underload_kg",
    "planned_payload_kg",
    "deferred_bag_weight_kg",
    "zero_fuel_weight_kg",
    "index_zfw",
    "mac_zfw_pct",
    "takeoff_weight_kg",
    "index_tow",
    "mac_tow_pct",
    "taxi_weight_kg",
    "landing_weight_kg",
    "underload_kg",
)


# -------------------------------------------------------------------- open
@bp.post("/load-plans")
@authorize("LoadController")
def create_load_plan():
    payload = validate.body()
    flight_id = validate.req_str(payload, "flight_id")
    expected = validate.req_int(payload, "expected_flight_version")
    row = {
        "flight_id": flight_id,
        "gate_bag_policy": validate.opt_enum(
            payload, "gate_bag_policy", GATE_BAG_POLICIES, default="ABSORB_INTO_UNDERLOAD"
        ),
        "offload_strategy": validate.opt_enum(
            payload, "offload_strategy", OFFLOAD_STRATEGIES, default="PRIORITY_FIRST"
        ),
        "rounding_mode": validate.opt_enum(
            payload, "rounding_mode", ROUNDING_MODES, default="PER_LINE_THEN_SUM"
        ),
        "status": "DRAFT",
        "restriction_status": "UNRESTRICTED",
        "envelope_ok": False,
        "_counted_cargo_ids": [],
    }
    for field in PLAN_ZERO_FIELDS:
        row[field] = 0

    flight = resolve.flight(flight_id)
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)
    if expected != int(flight["version"]):
        fail(ERR_STALE_FLIGHT_VERSION)

    existing = db.flight_plans(flight_id)
    row["revision_no"] = (
        max(int(p["revision_no"]) for p in existing) + 1 if existing else 1
    )

    for plan in existing:
        if plan["status"] not in balance.PLAN_ACTIVE_STATUSES:
            continue
        sheets = db.plan_sheets(plan["id"])
        if any(sheet["status"] in ("ACCEPTED", "AMENDED") for sheet in sheets):
            continue
        plan["status"] = "SUPERSEDED"
        db.touch(plan)
        for sheet in sheets:
            if sheet["status"] in ("ISSUED", "REJECTED_BY_CAPTAIN"):
                sheet["status"] = "SUPERSEDED"
                db.touch(sheet)

    db.touch(flight)
    return response.object_response(db.public(db.insert(db.load_plans, row)), 201)


@bp.get("/load-plans/<row_id>")
@authorize(*ANY_ROLE)
def read_load_plan(row_id):
    return response.object_response(db.public(resolve.load_plan(row_id)))


# ----------------------------------------------------------------- compute
@bp.post("/load-plans/<row_id>/compute")
@authorize("LoadController")
def compute_load_plan(row_id):
    plan = resolve.load_plan(row_id)
    flight, aircraft, program = balance.plan_context(plan)
    if flight["status"] != "PLANNING":
        fail(ERR_FLIGHT_INVALID_STATE)
    if plan["status"] != "DRAFT":
        fail(ERR_PLAN_INVALID_STATE)

    figures = balance.compute_figures(plan, flight, aircraft, program)
    if not figures["chain"]["envelope_ok"]:
        fail(ERR_CG_OUT_OF_ENVELOPE)

    balance.apply_row_updates(figures["row_updates"])
    plan["base_payload_kg"] = figures["base_payload_kg"]
    plan["frozen_underload_kg"] = figures["frozen_underload_kg"]
    plan["restriction_status"] = figures["restriction_status"]
    plan["planned_payload_kg"] = figures["planned_payload_kg"]
    plan["underload_kg"] = figures["underload_kg"]
    plan.update(figures["chain"])
    plan["_counted_cargo_ids"] = figures["counted_cargo_ids"]

    restricted = figures["restriction_status"] == "WEIGHT_RESTRICTED"
    plan["status"] = "RESTRICTED" if restricted else "COMPUTED"
    db.touch(plan)
    if not restricted:
        flight["status"] = "LOAD_CONTROLLED"
        db.touch(flight)
    return response.object_response(db.public(plan))


# ----------------------------------------------------------- offload preview
@bp.get("/load-plans/<row_id>/offload-preview")
@authorize("LoadControlAdmin", "LoadController")
def preview_offload(row_id):
    plan = resolve.load_plan(row_id)
    flight, _aircraft, _program = balance.plan_context(plan)
    excess, selected, relieved = balance.offload_selection(plan, flight)
    return response.object_response(
        {
            "strategy": plan["offload_strategy"],
            "excess_weight_kg": float(calc.r2(excess)),
            "offloaded_total_kg": float(relieved),
            "offloaded_piece_count": len(selected),
            "offloaded_awb_numbers": [item["awb_number"] for item in selected],
        }
    )


# ------------------------------------------------------------- apply offload
@bp.post("/load-plans/<row_id>/apply-offload")
@authorize("LoadController")
def apply_offload(row_id):
    plan = resolve.load_plan(row_id)
    flight, aircraft, _program = balance.plan_context(plan)
    if flight["status"] != "PLANNING":
        fail(ERR_FLIGHT_INVALID_STATE)
    if plan["status"] != "RESTRICTED":
        fail(ERR_PLAN_INVALID_STATE)

    excess, selected, relieved = balance.offload_selection(plan, flight)
    if relieved < excess:
        fail(ERR_OFFLOAD_INSUFFICIENT)

    selected_ids = {item["id"] for item in selected}
    figures = balance.live_figures(plan, flight, aircraft, exclude_cargo_ids=selected_ids)
    if not figures["chain"]["envelope_ok"]:
        fail(ERR_CG_OUT_OF_ENVELOPE)

    for item in selected:
        item["status"] = "OFFLOADED"
        item["assigned_compartment_id"] = None
        db.touch(item)

    plan["planned_payload_kg"] = figures["planned_payload_kg"]
    plan["underload_kg"] = figures["underload_kg"]
    plan.update(figures["chain"])
    plan["status"] = "COMPUTED"
    db.touch(plan)
    flight["status"] = "LOAD_CONTROLLED"
    db.touch(flight)
    return response.object_response(db.public(plan))


# ---------------------------------------------------------------- gate bags
@bp.post("/load-plans/<row_id>/gate-bags")
@authorize("RampAgent", "LoadController")
def present_gate_bag(row_id):
    payload = validate.body()
    awb_number = validate.req_str(payload, "awb_number")
    weight_kg = validate.req_num(payload, "weight_kg", gt=0)
    length_m = validate.req_num(payload, "length_m", gt=0)
    compartment_id = validate.req_str(payload, "compartment_id")

    plan = resolve.load_plan(row_id)
    flight, aircraft, _program = balance.plan_context(plan)
    compartment = resolve.compartment(compartment_id)

    if any(item["awb_number"] == awb_number for item in db.flight_cargo(flight["id"])):
        fail(ERR_DUPLICATE_KEY, "That air waybill number is already booked on the flight.")
    if plan["status"] != "COMPUTED":
        fail(ERR_PLAN_INVALID_STATE)
    if compartment["aircraft_id"] != flight["aircraft_id"]:
        fail(ERR_COMPARTMENT_NOT_ON_AIRCRAFT)
    if compartment["kind"] != "HOLD":
        fail(ERR_COMPARTMENT_KIND_MISMATCH)

    occupancy = balance.hold_occupancy(flight["id"], compartment_id)
    balance.check_hold_ceilings(compartment, occupancy + D(weight_kg))

    absorb = (
        plan["gate_bag_policy"] == "ABSORB_INTO_UNDERLOAD"
        and D(weight_kg) <= D(plan["underload_kg"])
    )

    row = {
        "flight_id": flight["id"],
        "awb_number": awb_number,
        "item_kind": "GATE_BAG",
        "weight_kg": weight_kg,
        "length_m": length_m,
        "is_dangerous_goods": False,
        "assigned_compartment_id": compartment_id if absorb else None,
        "offload_priority_rank": 4,
        "status": "ACCEPTED" if absorb else "DEFERRED",
    }

    if absorb:
        figures = balance.live_figures(
            plan,
            flight,
            aircraft,
            extra_gate_bag_kg=weight_kg,
            extra_gate_bag_arm_m=compartment["arm_m"],
        )
        if not figures["chain"]["envelope_ok"]:
            fail(ERR_CG_OUT_OF_ENVELOPE)
        item = db.insert(db.cargo_items, row)
        plan["planned_payload_kg"] = figures["planned_payload_kg"]
        plan["underload_kg"] = figures["underload_kg"]
        plan.update(figures["chain"])
    else:
        item = db.insert(db.cargo_items, row)
        plan["deferred_bag_weight_kg"] = float(
            calc.r2(D(plan["deferred_bag_weight_kg"]) + D(weight_kg))
        )
    db.touch(plan)
    return response.object_response(db.public(item), 201)
