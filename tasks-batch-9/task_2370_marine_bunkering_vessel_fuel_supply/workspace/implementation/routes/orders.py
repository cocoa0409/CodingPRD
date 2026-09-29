"""Delivery orders: scheduling, clearance, pumping and reconciliation."""

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, cascade, scheduling
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    q_str,
    v_datetime,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("orders", __name__)

ORDER_READERS = ("OpsCoordinator", "Surveyor", "BargeMaster", "CustomerRep")
LOGISTICS_STATUSES = (
    "SCHEDULED",
    "CLEARED",
    "PUMPING",
    "DELIVERED",
    "SUSPENDED",
    "CANCELLED",
)
MEASUREMENT_STATUSES = (
    "NOT_STARTED",
    "FIGURES_RECORDED",
    "AGREED",
    "DISPUTED",
    "RESURVEYED",
)
QUANTITY_DECISIONS = ("AGREE", "DISPUTE")


def _order_customer_id(order):
    nomination = calc.order_nomination(order)
    return nomination["customer_id"] if nomination else None


@bp.post("/delivery-orders")
@roles("OpsCoordinator")
def create_order():
    data = body()
    # PRD 2.7: asset_id resolves before nomination_id.
    asset = body_ref(data, "asset_id", store.delivery_assets, "ERR_ASSET_NOT_FOUND")
    nomination = body_ref(data, "nomination_id", store.nominations, "ERR_NOMINATION_NOT_FOUND")

    v_string(data, "nomination_id", min_len=1)
    v_string(data, "asset_id", min_len=1)
    planned_quantity_mt = v_decimal(data, "planned_quantity_mt", 3, positive=True)
    slot_start = v_datetime(data, "slot_start")
    slot_end = v_datetime(data, "slot_end")
    expected_nomination_version = v_int(data, "expected_nomination_version")

    if asset is None:
        raise ApiError("ERR_ASSET_NOT_FOUND")
    if nomination is None:
        raise ApiError("ERR_NOMINATION_NOT_FOUND")

    if expected_nomination_version != nomination["version"]:
        raise ApiError("ERR_STALE_NOMINATION_VERSION")
    if nomination["fulfillment_status"] not in ("CONFIRMED", "AWAITING_SCHEDULE"):
        raise ApiError("ERR_INVALID_NOMINATION_STATE")
    if asset["status"] == "QUARANTINED":
        raise ApiError("ERR_ASSET_QUARANTINED")

    port = store.ports.get(nomination["port_id"])
    grade = store.fuel_grades.get(nomination["grade_id"])
    if not calc.grade_compatible(asset, grade):
        raise ApiError("ERR_GRADE_INCOMPATIBLE_ASSET")
    if asset["home_port_id"] != nomination["port_id"] or (
        asset["asset_type"] != nomination["delivery_mode"]
    ):
        raise ApiError("ERR_ASSET_NOT_SUITABLE")

    scheduling.check_slot_in_window(nomination, slot_start, slot_end)
    if calc.asset_slot_conflict(asset, slot_start, slot_end):
        raise ApiError("ERR_ASSET_SLOT_CONFLICT")
    if calc.port_capacity_exceeded(port, slot_start, slot_end):
        raise ApiError("ERR_PORT_CAPACITY_EXCEEDED")
    scheduling.check_notice_period(port, slot_start)
    if planned_quantity_mt > asset["capacity_mt"]:
        raise ApiError("ERR_ASSET_CAPACITY_EXCEEDED")

    scheduling.supersede_orders(nomination)
    order = scheduling.create_order(
        nomination, asset, planned_quantity_mt, slot_start, slot_end
    )
    return success(serializers.delivery_order(order), 201)


@bp.get("/delivery-orders/<rec_id>")
@roles(*ORDER_READERS)
def get_order(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    return success(serializers.delivery_order(order))


@bp.get("/delivery-orders")
@roles(*ORDER_READERS)
def list_orders():
    nomination_id = q_str("nomination_id")
    asset_id = q_str("asset_id")
    logistics_status = q_enum("logistics_status", LOGISTICS_STATUSES)
    measurement_status = q_enum("measurement_status", MEASUREMENT_STATUSES)
    limit, offset = pagination()

    def match(row):
        if nomination_id is not None and row["nomination_id"] != nomination_id:
            return False
        if asset_id is not None and row["asset_id"] != asset_id:
            return False
        if logistics_status is not None and row["logistics_status"] != logistics_status:
            return False
        if measurement_status is not None and row["measurement_status"] != measurement_status:
            return False
        return True

    rows = db.sorted_rows(store.delivery_orders, match)
    page = apply_page(rows, limit, offset)
    return success_list(
        [serializers.delivery_order(r) for r in page], limit, offset, len(rows)
    )


@bp.post("/delivery-orders/<rec_id>/clear")
@roles("OpsCoordinator")
def clear_order(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    data = body()
    port_clearance_ref = v_string(data, "port_clearance_ref", min_len=1)

    nomination, port, grade, customer, asset = calc.order_context(order)
    if nomination["compliance_status"] != "APPROVED":
        raise ApiError("ERR_COMPLIANCE_NOT_APPROVED")
    if order["logistics_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if asset["status"] != "AVAILABLE":
        raise ApiError("ERR_ASSET_QUARANTINED")
    if calc.open_spill_incidents(asset["id"]):
        raise ApiError("ERR_OPEN_SPILL_INCIDENT")
    if customer["credit_status"] == "HOLD":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")

    order["logistics_status"] = "CLEARED"
    order["port_clearance_ref"] = port_clearance_ref
    order["cleared_at"] = db.now()
    touch(order)
    return success(serializers.delivery_order(order))


@bp.post("/delivery-orders/<rec_id>/start-pumping")
@roles("BargeMaster")
def start_pumping(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if g.user_id != order["asset_id"]:
        raise ApiError("ERR_ASSET_NOT_ASSIGNED")

    nomination, port, grade, customer, asset = calc.order_context(order)
    if order["logistics_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if asset["status"] != "AVAILABLE":
        raise ApiError("ERR_ASSET_QUARANTINED")
    if not asset["boom_certified"]:
        raise ApiError("ERR_BOOM_NOT_CERTIFIED")
    if not calc.grade_compatible(asset, grade):
        raise ApiError("ERR_GRADE_INCOMPATIBLE_ASSET")
    if db.now() < order["slot_start"]:
        raise ApiError("ERR_SLOT_OUTSIDE_WINDOW")

    order["logistics_status"] = "PUMPING"
    touch(order)
    asset["last_grade_id"] = nomination["grade_id"]
    touch(asset)
    return success(serializers.delivery_order(order))


@bp.post("/delivery-orders/<rec_id>/complete-pumping")
@roles("BargeMaster")
def complete_pumping(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if g.user_id != order["asset_id"]:
        raise ApiError("ERR_ASSET_NOT_ASSIGNED")
    data = body()
    barge_sounding_mt = v_decimal(data, "barge_sounding_mt", 3, positive=True)
    vessel_sounding_mt = v_decimal(data, "vessel_sounding_mt", 3, positive=True)
    meter_mt = v_decimal(data, "meter_mt", 3, positive=True)

    nomination, port, grade, customer, asset = calc.order_context(order)
    if order["logistics_status"] != "PUMPING":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if barge_sounding_mt > asset["capacity_mt"]:
        raise ApiError("ERR_ASSET_CAPACITY_EXCEEDED")
    if abs(barge_sounding_mt - meter_mt) > calc.MEASUREMENT_TOLERANCE_MT:
        raise ApiError("ERR_MEASUREMENT_FIGURES_INCONSISTENT")

    order["barge_sounding_mt"] = barge_sounding_mt
    order["vessel_sounding_mt"] = vessel_sounding_mt
    order["meter_mt"] = meter_mt
    order["logistics_status"] = "DELIVERED"
    order["measurement_status"] = "FIGURES_RECORDED"
    if customer["settlement_basis"] == "SUPPLIER_FIGURES":
        calc.apply_supplier_figures(order)
    touch(order)

    cascade.refresh_asset(asset, score=True)
    if nomination["fulfillment_status"] == "SCHEDULED":
        nomination["fulfillment_status"] = "DELIVERED"
        touch(nomination)
    return success(serializers.delivery_order(order))


@bp.post("/delivery-orders/<rec_id>/joint-survey")
@roles("Surveyor")
def joint_survey(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    data = body()
    surveyed_mt = v_decimal(data, "surveyed_mt", 3, positive=True)

    if order["logistics_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["measurement_status"] not in ("FIGURES_RECORDED", "DISPUTED"):
        raise ApiError("ERR_INVALID_MEASUREMENT_STATE")

    order["surveyed_mt"] = surveyed_mt
    order["measurement_status"] = "RESURVEYED"
    touch(order)
    return success(serializers.delivery_order(order))


@bp.post("/delivery-orders/<rec_id>/quantity-decision")
@roles("Surveyor", "CustomerRep")
def quantity_decision(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if g.role == "CustomerRep" and g.user_id != _order_customer_id(order):
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
    data = body()
    decision = v_enum(data, "decision", QUANTITY_DECISIONS)

    # The two branches belong to different desks (PRD 3.5).
    if decision == "AGREE" and g.role != "Surveyor":
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if decision == "DISPUTE" and g.role != "CustomerRep":
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    if decision == "AGREE":
        if order["measurement_status"] != "RESURVEYED" or order["surveyed_mt"] is None:
            raise ApiError("ERR_INVALID_MEASUREMENT_STATE")
        calc.apply_joint_survey(order)
    else:
        if order["measurement_status"] != "AGREED":
            raise ApiError("ERR_INVALID_MEASUREMENT_STATE")
        if calc.issued_note_of_order(order["id"]) is not None:
            raise ApiError("ERR_BDN_ALREADY_ISSUED")
        if not (order["vessel_sounding_mt"] is not None
                and order["barge_sounding_mt"] is not None
                and order["vessel_sounding_mt"] < order["barge_sounding_mt"]):
            raise ApiError("ERR_NO_MEASUREMENT_DISCREPANCY")
        order["measurement_status"] = "DISPUTED"
        order["agreed_quantity_mt"] = None
        order["measurement_basis"] = None
        order["shortfall_mt"] = None

    touch(order)
    return success(serializers.delivery_order(order))


@bp.post("/delivery-orders/<rec_id>/cancel")
@roles("OpsCoordinator")
def cancel(rec_id):
    order = path_ref(store.delivery_orders, rec_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if order["logistics_status"] not in ("SCHEDULED", "CLEARED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ORDER_STATE")
    cascade.cancel_order(order)
    return success(serializers.delivery_order(order))
