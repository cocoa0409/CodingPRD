"""Processing centers, dwell metrics, kit receipt and hold application."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid
from middleware import OPS_ROLES, ROLE_MANAGER, ROLE_PLANNER, ROLE_TECH, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("centers", __name__)


# ------------------------------------------------------------------- create
@bp.route("/vpc/processing-centers", methods=["POST"])
def create_center():
    authenticate([ROLE_PLANNER])
    body = v.body()
    name = v.req_str(body, "name")
    port_code = v.req_str(body, "port_code")
    capacity = v.req_int(body, "yard_capacity_slots", minimum=1)
    daily_rate = v.req_int(body, "daily_storage_rate_cents", minimum=0)
    labor_rate = v.req_int(body, "labor_rate_cents_per_hour", minimum=0)
    fuel_pct = v.req_rate(body, "fuel_surcharge_pct", 0, 0.5, 4)
    free_days = v.opt_int(body, "free_storage_days", default=5, minimum=0)

    if any(c["port_code"] == port_code for c in db.centers.values()):
        fail("ERR_DUPLICATE_KEY", "port_code %s already exists" % port_code)

    record = db.base_record()
    record.update(
        {
            "name": name,
            "port_code": port_code,
            "yard_capacity_slots": capacity,
            "yard_occupied_slots": 0,
            "yard_free_slots": capacity,
            "yard_posture": calc.yard_posture(0, capacity),
            "free_storage_days": free_days,
            "daily_storage_rate_cents": daily_rate,
            "labor_rate_cents_per_hour": labor_rate,
            "fuel_surcharge_pct": fuel_pct,
            "provisional_storage_accrued_cents": 0,
            "realized_storage_revenue_cents": 0,
            "repair_spend_cents": 0,
        }
    )
    db.centers[record["id"]] = record
    return object_response(ser.center(record), 201)


# --------------------------------------------------------------------- read
@bp.route("/vpc/processing-centers/<center_id>", methods=["GET"])
def read_center(center_id):
    authenticate(OPS_ROLES)
    center = db.must_get("centers", center_id)
    state.recompute_center(center)
    return object_response(ser.center(center))


@bp.route("/vpc/processing-centers", methods=["GET"])
def list_centers():
    authenticate(OPS_ROLES)
    port_code = v.query_filter("port_code")
    posture = v.query_filter("yard_posture")
    records = db.ordered(db.centers)
    for center in records:
        state.recompute_center(center)
    if port_code is not None:
        records = [c for c in records if c["port_code"] == port_code]
    if posture is not None:
        records = [c for c in records if c["yard_posture"] == posture]
    items, limit, offset, total = v.paginate(records, ser.center)
    return list_response(items, limit, offset, total)


# ------------------------------------------------------------ dwell metrics
@bp.route("/vpc/processing-centers/<center_id>/dwell-metrics", methods=["GET"])
def dwell_metrics(center_id):
    authenticate(OPS_ROLES)
    center = db.must_get("centers", center_id)
    now = db.clock_now()
    rows = []
    for model_line in calc.MODEL_LINES:
        units = [
            veh
            for veh in db.ordered(db.vehicles)
            if veh["processing_center_id"] == center["id"]
            and veh["yard_presence"] == "IN_YARD"
            and veh["model_line"] == model_line
        ]
        dwell = [calc.dwell_days(veh["yard_in_at"], now) for veh in units]
        unit_count = len(units)
        rows.append(
            {
                "model_line": model_line,
                "unit_count": unit_count,
                "avg_dwell_days": calc.avg_dwell_days(sum(dwell), unit_count),
                "aging_0_15": len([d for d in dwell if d <= 15]),
                "aging_16_30": len([d for d in dwell if 16 <= d <= 30]),
                "aging_31_plus": len([d for d in dwell if d >= 31]),
                "blocked_count": len(
                    [
                        veh
                        for veh in units
                        if veh["stop_ship_blocked"]
                        or veh["damage_status"] in ("SURVEY_DAMAGE_OPEN", "REPAIR_AUTHORIZED")
                    ]
                ),
                "accrued_storage_cents": sum(
                    veh["storage_charge_provisional_cents"] for veh in units
                ),
            }
        )
    return object_response({"rows": rows})


# --------------------------------------------------------- kit stock receipt
@bp.route("/vpc/processing-centers/<center_id>/accessory-kits", methods=["POST"])
def create_kit(center_id):
    authenticate([ROLE_TECH])
    center = db.must_get("centers", center_id)
    body = v.body()
    kit_code = v.req_str(body, "kit_code")
    program_code = v.req_str(body, "program_code")
    received = v.req_int(body, "received_qty_total", minimum=0)
    unit_cost = v.req_int(body, "unit_cost_cents", minimum=0)
    install_minutes = v.req_int(body, "install_minutes_per_unit", minimum=0)

    if any(
        k["processing_center_id"] == center["id"] and k["kit_code"] == kit_code
        for k in db.kits.values()
    ):
        fail("ERR_DUPLICATE_KEY", "kit_code %s already exists at this center" % kit_code)

    record = db.base_record()
    record.update(
        {
            "processing_center_id": center["id"],
            "kit_code": kit_code,
            "program_code": program_code,
            "received_qty_total": received,
            "on_hand_qty": received,
            "reserved_qty": 0,
            "available_qty": received,
            "consumed_qty": 0,
            "unit_cost_cents": unit_cost,
            "install_minutes_per_unit": install_minutes,
        }
    )
    db.kits[record["id"]] = record
    return object_response(ser.kit(record), 201)


# ----------------------------------------------------------- hold application
@bp.route("/vpc/processing-centers/<center_id>/hold-orders", methods=["POST"])
def create_hold(center_id):
    user_id, _role = authenticate([ROLE_MANAGER])
    center = db.must_get("centers", center_id)
    body = v.body()

    # Band 4: the SINGLE_VIN target is a body foreign key.
    raw_scope = body.get("scope_type")
    raw_vehicle_id = body.get("vehicle_id")
    target_vehicle = None
    if raw_scope == "SINGLE_VIN" and raw_vehicle_id is not None:
        target_vehicle = db.vehicles.get(raw_vehicle_id)
        if target_vehicle is None:
            fail("ERR_REFERENCE_NOT_FOUND", "vehicle_id does not resolve")

    # Band 5: schema and targeting-field agreement.
    hold_type = v.req_enum(body, "hold_type", ("RECALL", "STOP_SHIP"))
    scope_type = v.req_enum(body, "scope_type", ("MODEL_LINE", "SINGLE_VIN"))
    reference_code = v.req_str(body, "reference_code")
    model_line = None
    vehicle_id = None
    if scope_type == "MODEL_LINE":
        if v.present(body, "vehicle_id"):
            invalid("a MODEL_LINE hold must not carry vehicle_id")
        model_line = v.req_enum(body, "model_line", calc.MODEL_LINES)
    else:
        if v.present(body, "model_line"):
            invalid("a SINGLE_VIN hold must not carry model_line")
        if not v.present(body, "vehicle_id"):
            invalid("vehicle_id is required for a SINGLE_VIN hold")
        vehicle_id = body["vehicle_id"]

    record = db.base_record()
    record.update(
        {
            "processing_center_id": center["id"],
            "hold_type": hold_type,
            "scope_type": scope_type,
            "model_line": model_line,
            "vehicle_id": vehicle_id,
            "reference_code": reference_code,
            "affected_vehicle_count": 0,
            "applied_by_user_id": user_id,
            "lifted_by_user_id": None,
            "status": "OPEN",
        }
    )
    db.hold_orders[record["id"]] = record

    # LINK 2: block every in-scope unit still in the yard.
    if scope_type == "MODEL_LINE":
        in_scope = [
            veh
            for veh in db.ordered(db.vehicles)
            if veh["processing_center_id"] == center["id"]
            and veh["model_line"] == model_line
            and veh["yard_presence"] == "IN_YARD"
        ]
    else:
        in_scope = [target_vehicle] if target_vehicle["yard_presence"] == "IN_YARD" else []

    affected = []
    for veh in in_scope:
        veh["stop_ship_blocked"] = True
        veh["blocking_hold_order_id"] = record["id"]
        db.touch(veh)
        affected.append(veh)
    record["affected_vehicle_count"] = len(affected)

    # LINK 3 + LINK 4: cancel ALLOCATED orders of those units, unwind commitments.
    affected_ids = {veh["id"] for veh in affected}
    for order in db.ordered(db.release_orders):
        if order["vehicle_id"] in affected_ids and order["status"] == "ALLOCATED":
            state.unwind_release_order(order, "CANCELLED_BY_HOLD", hold_order_id=record["id"])

    for veh in affected:
        veh_center = state.center_of_vehicle(veh)
        if veh_center is not None:
            state.recompute_center(veh_center)
    state.recompute_center(center)
    return object_response(ser.hold_order(record), 201)
