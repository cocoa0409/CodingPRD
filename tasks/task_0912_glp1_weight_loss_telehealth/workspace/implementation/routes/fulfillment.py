"""Routing, reservation, shipment and cancellation of pharmacy orders (PRD 3.7)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard, require_owner
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch

bp = Blueprint("fulfillment", __name__)


@bp.post("/pharmacy-orders")
def create_pharmacy_order():
    guard(["Provider"])
    body = v.body()

    prescription_id = v.string_field(body, "prescription_id", required=True)
    titration_step_id = v.string_field(body, "titration_step_id", required=True)
    units_requested = v.int_field(body, "units_requested", required=True,
                                  minimum=1, maximum=calc.MAX_UNITS_PER_ORDER)
    window_start_at = v.datetime_field(body, "window_start_at", required=True)
    window_end_at = v.datetime_field(body, "window_end_at", required=True)
    v.interval(window_start_at, window_end_at, "window_start_at", "window_end_at")
    expected_prescription_version = v.int_field(body, "expected_prescription_version",
                                                required=True)

    prescription = services.get_prescription(prescription_id)
    services.get_titration_step(titration_step_id)

    if expected_prescription_version != prescription["version"]:
        raise ApiError(errors.ERR_STALE_PRESCRIPTION_VERSION)

    if prescription["clinical_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PRESCRIPTION_NOT_ACTIVE)

    patient = services.get_patient(prescription["patient_id"])

    # Routing runs first; only if it produced a lot does the unit ceiling run.
    lot, required_form = services.select_supply_lot(prescription, patient,
                                                   units_requested)
    if lot is None:
        raise ApiError(errors.ERR_NO_ELIGIBLE_SUPPLY_LOT)

    if units_requested > calc.MAX_UNITS_PER_ORDER \
            or units_requested > prescription["units_per_cycle"]:
        raise ApiError(errors.ERR_UNITS_EXCEED_LIMIT)

    order = new_record(store.pharmacy_orders, {
        "prescription_id": prescription_id,
        "titration_step_id": titration_step_id,
        "pharmacy_id": lot["pharmacy_id"],
        "supply_lot_id": lot["id"],
        "units_requested": units_requested,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "status": "CREATED",
        "dispense_type_at_route": required_form,
        "reserved_at": None,
        "shipped_at": None,
        "cancel_reason": None,
    })

    prescription["fulfillment_status"] = "ROUTED"
    touch(prescription)

    return envelope.success(serializers.dump("pharmacy_order", order), 201)


@bp.get("/pharmacy-orders/<pharmacy_order_id>")
def read_pharmacy_order(pharmacy_order_id):
    guard(ANY_ROLE)
    order = services.get_pharmacy_order(pharmacy_order_id)
    return envelope.success(serializers.dump("pharmacy_order", order), 200)


@bp.get("/pharmacy-orders")
def list_pharmacy_orders():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("prescription_id", "titration_step_id", "pharmacy_id",
                              "supply_lot_id", "status")
    records = v.apply_filters(ordered(list(store.pharmacy_orders.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("pharmacy_order", page),
                               limit, offset, total)


@bp.post("/pharmacy-orders/<pharmacy_order_id>/reserve")
def reserve_pharmacy_order(pharmacy_order_id):
    user_id, _role = guard(["PharmacyOperator"])
    order = services.get_pharmacy_order(pharmacy_order_id)
    require_owner(order["pharmacy_id"] == user_id)

    if order["status"] != "CREATED":
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(order["prescription_id"])
    if prescription["clinical_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PRESCRIPTION_NOT_ACTIVE)

    lot = services.get_supply_lot(order["supply_lot_id"])
    if lot["available_units"] < order["units_requested"]:
        raise ApiError(errors.ERR_LOT_CAPACITY_EXCEEDED)

    start = parse_iso(order["window_start_at"])
    end = parse_iso(order["window_end_at"])
    committed = order["units_requested"]
    for other in store.pharmacy_orders.values():
        if other["id"] == order["id"] or other["status"] != "RESERVED":
            continue
        if other["supply_lot_id"] != order["supply_lot_id"]:
            continue
        other_start = parse_iso(other["window_start_at"])
        other_end = parse_iso(other["window_end_at"])
        if start < other_end and other_start < end:
            committed += other["units_requested"]
    if committed > lot["window_capacity_units"]:
        raise ApiError(errors.ERR_LOT_CAPACITY_EXCEEDED)

    order["status"] = "RESERVED"
    order["reserved_at"] = store.now_iso()
    touch(order)

    lot["available_units"] -= order["units_requested"]
    lot["reserved_units"] += order["units_requested"]
    touch(lot)

    return envelope.success(serializers.dump("pharmacy_order", order), 200)


@bp.post("/pharmacy-orders/<pharmacy_order_id>/ship")
def ship_pharmacy_order(pharmacy_order_id):
    user_id, _role = guard(["PharmacyOperator"])
    order = services.get_pharmacy_order(pharmacy_order_id)
    require_owner(order["pharmacy_id"] == user_id)

    if order["status"] != "RESERVED":
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(order["prescription_id"])
    if prescription["clinical_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PRESCRIPTION_NOT_ACTIVE)

    if order["dispense_type_at_route"] == "BRANDED" \
            and prescription["active_route_mode"] == "INSURANCE":
        now = store.now_dt()
        covered = False
        for authorization in store.prior_authorizations.values():
            if authorization["prescription_id"] != prescription["id"]:
                continue
            if authorization["status"] != "APPROVED":
                continue
            through = parse_iso(authorization["approved_through_at"])
            if through is not None and through >= now:
                covered = True
                break
        if not covered:
            raise ApiError(errors.ERR_PRIOR_AUTH_REQUIRED)

    order["status"] = "SHIPPED"
    order["shipped_at"] = store.now_iso()
    touch(order)

    lot = services.get_supply_lot(order["supply_lot_id"])
    lot["reserved_units"] -= order["units_requested"]
    lot["dispensed_units"] += order["units_requested"]
    touch(lot)

    prescription["fulfillment_status"] = "DISPENSED"
    touch(prescription)

    return envelope.success(serializers.dump("pharmacy_order", order), 200)


@bp.post("/pharmacy-orders/<pharmacy_order_id>/cancel")
def cancel_pharmacy_order(pharmacy_order_id):
    guard(["PharmacyOperator", "Provider"])
    order = services.get_pharmacy_order(pharmacy_order_id)

    if order["status"] not in ("CREATED", "RESERVED"):
        raise ApiError(errors.ERR_INVALID_STATE)

    services.cancel_order(order, "OPERATOR")
    return envelope.success(serializers.dump("pharmacy_order", order), 200)
