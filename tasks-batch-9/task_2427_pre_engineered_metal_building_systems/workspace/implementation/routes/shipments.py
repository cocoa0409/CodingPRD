"""PRD 3.9 -- sequencing truckloads to the erection crew."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, new_row, now_iso, ordered, touch

bp = Blueprint("shipments", __name__)


def _site_loads(order):
    """Every active load at the same job site, across every builder's orders."""
    site_order_ids = set(
        o["id"] for o in db.orders.values() if o["job_site_code"] == order["job_site_code"]
    )
    return [
        load
        for load in ordered(db.shipment_loads)
        if load["order_id"] in site_order_ids and load["status"] in C.ACTIVE_LOAD_STATUSES
    ]


@bp.route("/shipment-loads", methods=["POST"])
@roles_required("LogisticsCoordinator")
def create_shipment_load():
    data = V.body()
    order_id = V.get_string(data, "order_id")
    carrier_name = V.get_string(data, "carrier_name", min_len=1)
    erection_stage = V.get_enum(data, "erection_stage", C.ERECTION_STAGES)
    component_marks = V.get_string_array(data, "component_marks")
    window_start, window_start_raw = V.get_datetime(data, "unload_window_start")
    window_end, window_end_raw = V.get_datetime(data, "unload_window_end")
    expected_version = V.get_int(data, "expected_order_version")

    order = domain.get_order(order_id)

    # Band 6.
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")

    # Band 10 -- a load may be planned against an order already finished in the plant.
    if order["production_status"] not in (
        "PROD_RELEASED",
        "PROD_IN_FABRICATION",
        "PROD_COMPLETE",
    ):
        raise ApiError("ERR_ORDER_NOT_RELEASED")

    # Band 12 -- resolve every mark against the order's design, then check stage.
    design_id = order["engineering_design_id"]
    by_mark = {}
    if design_id is not None:
        for component in domain.components_of_design(design_id):
            by_mark[component["mark"]] = component

    resolved = []
    for mark in component_marks:
        component = by_mark.get(mark)
        if component is None:
            raise ApiError("ERR_MARK_NOT_FOUND")
        resolved.append(component)
    for component in resolved:
        if component["erection_stage"] != erection_stage:
            raise ApiError("ERR_LOAD_ITEM_STAGE_MISMATCH")

    # Band 13 -- closed window, so equal bounds are valid.
    if window_end < window_start:
        raise ApiError("ERR_INVALID_WINDOW_RANGE")

    # Band 14 -- internal repetition, then cross-load exclusivity, then site capacity.
    if len(set(component_marks)) != len(component_marks):
        raise ApiError("ERR_DUPLICATE_MARK")

    taken = set()
    for load in domain.loads_of_order(order["id"]):
        if load["status"] in C.ACTIVE_LOAD_STATUSES:
            taken.update(load["component_marks"])
    for mark in component_marks:
        if mark in taken:
            raise ApiError("ERR_MARK_ALREADY_ASSIGNED")

    overlapping = 0
    for load in _site_loads(order):
        if window_start <= load["_unload_end_dt"] and load["_unload_start_dt"] <= window_end:
            overlapping += 1
    if overlapping >= order["site_delivery_capacity"]:
        raise ApiError("ERR_SITE_UNLOAD_CAPACITY_EXCEEDED")

    row = new_row(
        {
            "order_id": order["id"],
            "carrier_name": carrier_name,
            "erection_stage": erection_stage,
            "component_marks": list(component_marks),
            "stage_sequence": C.ERECTION_STAGE_SEQUENCE[erection_stage],
            "gross_weight_lbs": calc.shipment_load_gross_weight(resolved),
            "unload_window_start": window_start_raw,
            "unload_window_end": window_end_raw,
            "_unload_start_dt": window_start,
            "_unload_end_dt": window_end,
            "status": "PLANNED",
            "dispatched_at": None,
        }
    )
    db.shipment_loads[row["id"]] = row

    domain.recompute_weight_ledger(order)
    touch(order)
    return object_response(S.shipment_load_out(row), 201)


@bp.route("/shipment-loads/<load_id>", methods=["GET"])
@roles_required(ANY)
def read_shipment_load(load_id):
    return object_response(S.shipment_load_out(domain.get_shipment_load(load_id)))


@bp.route("/shipment-loads", methods=["GET"])
@roles_required(ANY)
def list_shipment_loads():
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    erection_stage = request.args.get("erection_stage")

    def predicate(row):
        if order_id is not None and row["order_id"] != order_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if erection_stage is not None and row["erection_stage"] != erection_stage:
            return False
        return True

    return paginated(ordered(db.shipment_loads, predicate), S.shipment_load_out)


@bp.route("/shipment-loads/<load_id>/dispatch", methods=["POST"])
@roles_required("LogisticsCoordinator")
def dispatch_shipment_load(load_id):
    load = domain.get_shipment_load(load_id)

    # Band 9.
    if load["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    order = db.orders.get(load["order_id"])
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    # Band 10 -- production state, then the fabrication step behind the stage.
    if order["production_status"] not in (
        "PROD_RELEASED",
        "PROD_IN_FABRICATION",
        "PROD_COMPLETE",
    ):
        raise ApiError("ERR_ORDER_NOT_RELEASED")

    required_lot_type = C.LOT_TYPE_FOR_STAGE.get(load["erection_stage"])
    if required_lot_type is not None:
        complete = [
            lot
            for lot in domain.lots_of_order(order["id"])
            if lot["lot_type"] == required_lot_type and lot["status"] == "COMPLETE"
        ]
        if not complete:
            raise ApiError("ERR_LOT_NOT_COMPLETE")

    # Band 14 -- no earlier-stage load of the same order may still be PLANNED.
    for other in domain.loads_of_order(order["id"]):
        if other["id"] == load["id"]:
            continue
        if other["status"] == "PLANNED" and other["stage_sequence"] < load["stage_sequence"]:
            raise ApiError("ERR_ERECTION_SEQUENCE_VIOLATION")

    load["status"] = "DISPATCHED"
    load["dispatched_at"] = now_iso()
    touch(load)
    # The weight ledger is deliberately untouched: a dispatched load is still assigned.
    return object_response(S.shipment_load_out(load))


@bp.route("/shipment-loads/<load_id>/cancel", methods=["POST"])
@roles_required("LogisticsCoordinator")
def cancel_shipment_load(load_id):
    load = domain.get_shipment_load(load_id)

    if load["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    load["status"] = "CANCELLED"
    touch(load)

    order = db.orders.get(load["order_id"])
    if order is not None:
        domain.recompute_weight_ledger(order)
        domain.production_status_rollup(order)
        touch(order)
    return object_response(S.shipment_load_out(load))
