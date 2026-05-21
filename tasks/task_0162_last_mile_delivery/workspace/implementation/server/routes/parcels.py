"""Parcel endpoints: CRUD, induct-to-hub, sort, attempts, reattempt, return-to-sender."""
from decimal import Decimal

from flask import Blueprint, request

from .. import store
from ..auth import authed
from ..clock import clock, parse_iso8601
from ..envelope import success_array, success_object
from ..errors import raise_error
from ..serializers import (
    serialize_delivery_attempt,
    serialize_parcel,
)
from ..services.calculations import (
    CUSTOMER_REDELIVERY_CAP_30D,
    MAX_REDELIVERY_ATTEMPTS,
    dec2,
    shipping_fee_final,
    shipping_fee_quote,
)
from ..services.rolling import recompute_customer_rolling
from ..services.route_planner import (
    assign_planned_times,
    recompute_route_derived,
    stops_for_route_sorted,
)
from ..services.tracking import mint_tracking_number
from ._helpers import (
    check_version,
    get_json_body,
    parse_pagination,
    require,
)


bp = Blueprint("parcels", __name__)


VALID_HAZMAT_CLASSES = {"NONE", "CLASS_2", "CLASS_3", "CLASS_4", "CLASS_8", "CLASS_9"}
VALID_PARCEL_STATUSES = {
    "INDUCTED",
    "IN_TRANSIT_HUB",
    "SORTED",
    "ON_VEHICLE",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "EXCEPTION",
    "RETURNED_TO_SENDER",
}
SUCCESS_OUTCOMES = {"DELIVERED_SIGNED", "DRIVER_RELEASED"}
FAILURE_OUTCOMES = {"NO_ONE_HOME", "REFUSED", "ADDRESS_INVALID", "HAZMAT_BLOCKED"}
ALL_OUTCOMES = SUCCESS_OUTCOMES | FAILURE_OUTCOMES


def _validate_weight(weight_kg):
    try:
        wt = float(weight_kg)
    except Exception:
        raise_error("ERR_PARCEL_WEIGHT_OUT_OF_RANGE")
    if wt <= 0 or wt > 70.0:
        raise_error("ERR_PARCEL_WEIGHT_OUT_OF_RANGE")
    return wt


def _validate_declared_value(declared_value):
    try:
        dv = Decimal(str(declared_value))
    except Exception:
        raise_error("ERR_DECLARED_VALUE_OUT_OF_RANGE")
    if dv < Decimal("0") or dv > Decimal("50000.00"):
        raise_error("ERR_DECLARED_VALUE_OUT_OF_RANGE")
    return dv


def _validate_hazmat(hazmat_class):
    if hazmat_class is None:
        return "NONE"
    if hazmat_class not in VALID_HAZMAT_CLASSES:
        raise_error("ERR_REFERENCE_NOT_FOUND", "hazmat_class invalid")
    return hazmat_class


def _validate_time_windows(start_raw, end_raw):
    try:
        start = parse_iso8601(start_raw)
        end = parse_iso8601(end_raw)
    except Exception:
        raise_error("ERR_REFERENCE_NOT_FOUND", "invalid time_window timestamps")
    if start >= end:
        raise_error("ERR_REFERENCE_NOT_FOUND", "time_window_start must be < time_window_end")
    return start_raw, end_raw


def _recompute_parcel_quote(parcel: dict):
    addr = store.addresses.get(parcel.get("destination_address_id"))
    center = store.transit_centers.get(parcel.get("origin_center_id"))
    if not addr or not center:
        return
    quoted = shipping_fee_quote(parcel, addr, center)
    parcel["quoted_fee"] = quoted


@bp.post("/parcels")
@authed(["Dispatcher", "SortingHubOperator"])
def create_parcel(user_id, user_role):
    body = get_json_body()
    customer_id = require(body, "customer_id")
    origin_center_id = require(body, "origin_center_id")
    weight_kg = require(body, "weight_kg")
    declared_value = require(body, "declared_value")
    time_window_start = require(body, "time_window_start")
    time_window_end = require(body, "time_window_end")
    destination_address_id = body.get("destination_address_id")
    signature_required = bool(body.get("signature_required", False))
    hazmat_class = body.get("hazmat_class", "NONE") or "NONE"

    with store.lock:
        # FK existence
        customer = store.customers.get(customer_id)
        if not customer:
            raise_error("ERR_REFERENCE_NOT_FOUND", "customer_id not found")
        center = store.transit_centers.get(origin_center_id)
        if not center:
            raise_error("ERR_REFERENCE_NOT_FOUND", "origin_center_id not found")

        if destination_address_id is None:
            destination_address_id = customer.get("default_address_id")
        if not destination_address_id:
            raise_error(
                "ERR_REFERENCE_NOT_FOUND",
                "destination_address_id required and customer has no default",
            )
        addr = store.addresses.get(destination_address_id)
        if not addr:
            raise_error("ERR_REFERENCE_NOT_FOUND", "destination_address_id not found")
        if addr["customer_id"] != customer_id:
            raise_error(
                "ERR_REFERENCE_NOT_FOUND",
                "destination_address does not belong to customer",
            )

        hazmat_class = _validate_hazmat(hazmat_class)
        _validate_time_windows(time_window_start, time_window_end)
        weight = _validate_weight(weight_kg)
        dv = _validate_declared_value(declared_value)

        existing_tn = {p["tracking_number"] for p in store.parcels.values()}
        parcel = {
            "tracking_number": mint_tracking_number(existing_tn),
            "customer_id": customer_id,
            "destination_address_id": destination_address_id,
            "origin_center_id": origin_center_id,
            "weight_kg": weight,
            "declared_value": dec2(dv),
            "signature_required": signature_required,
            "hazmat_class": hazmat_class,
            "time_window_start": time_window_start,
            "time_window_end": time_window_end,
            "status": "INDUCTED",
            "redelivery_attempts": 0,
            "quoted_fee": Decimal("0.00"),
            "final_fee": None,
            "last_attempt_outcome": "NONE",
        }
        store.stamp_create(parcel)
        _recompute_parcel_quote(parcel)
        store.parcels[parcel["id"]] = parcel
        return success_object(serialize_parcel(parcel), status=201)


@bp.get("/parcels/<pid>")
@authed(["Customer", "Dispatcher", "Driver", "SortingHubOperator", "ComplianceOfficer"])
def read_parcel(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if user_role == "Customer" and parcel["customer_id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        if user_role == "Driver":
            # Driver may read parcels on routes assigned to them.
            allowed = False
            for stop in store.route_stops.values():
                if stop["parcel_id"] != pid:
                    continue
                route = store.routes.get(stop["route_id"])
                if route and route.get("driver_id") == user_id:
                    allowed = True
                    break
            if not allowed:
                raise_error("ERR_FORBIDDEN")
        return success_object(serialize_parcel(parcel))


@bp.get("/parcels")
@authed(["Dispatcher", "SortingHubOperator", "ComplianceOfficer"])
def list_parcels(user_id, user_role):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    customer_filter = request.args.get("customer_id")
    origin_filter = request.args.get("origin_center_id")
    hazmat_filter = request.args.get("hazmat_class")

    if status_filter and status_filter not in VALID_PARCEL_STATUSES:
        raise_error("ERR_REFERENCE_NOT_FOUND", "status filter invalid")
    if hazmat_filter and hazmat_filter not in VALID_HAZMAT_CLASSES:
        raise_error("ERR_REFERENCE_NOT_FOUND", "hazmat_class filter invalid")

    with store.lock:
        items = list(store.parcels.values())
        if status_filter:
            items = [p for p in items if p["status"] == status_filter]
        if customer_filter:
            items = [p for p in items if p["customer_id"] == customer_filter]
        if origin_filter:
            items = [p for p in items if p["origin_center_id"] == origin_filter]
        if hazmat_filter:
            items = [p for p in items if p.get("hazmat_class", "NONE") == hazmat_filter]
        items.sort(key=lambda p: p["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return success_array(
            [serialize_parcel(p) for p in page], limit, offset, total
        )


@bp.patch("/parcels/<pid>")
@authed(["Dispatcher", "SortingHubOperator"])
def update_parcel(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if parcel["status"] not in ("INDUCTED", "IN_TRANSIT_HUB"):
            raise_error("ERR_INVALID_STATE", "parcel not editable in current state")
        body = get_json_body()
        check_version(body, parcel)

        # Validate fiscal range fields before applying anything.
        if "weight_kg" in body:
            _validate_weight(body["weight_kg"])
        if "declared_value" in body:
            _validate_declared_value(body["declared_value"])
        if "hazmat_class" in body:
            _validate_hazmat(body["hazmat_class"])
        if "destination_address_id" in body:
            new_addr_id = body["destination_address_id"]
            if new_addr_id is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "destination_address_id required")
            addr = store.addresses.get(new_addr_id)
            if not addr:
                raise_error("ERR_REFERENCE_NOT_FOUND", "destination_address_id not found")
            if addr["customer_id"] != parcel["customer_id"]:
                raise_error(
                    "ERR_REFERENCE_NOT_FOUND",
                    "destination_address does not belong to parcel customer",
                )
        if "time_window_start" in body or "time_window_end" in body:
            new_start = body.get("time_window_start", parcel["time_window_start"])
            new_end = body.get("time_window_end", parcel["time_window_end"])
            _validate_time_windows(new_start, new_end)

        # Apply
        if "weight_kg" in body:
            parcel["weight_kg"] = float(body["weight_kg"])
        if "declared_value" in body:
            parcel["declared_value"] = dec2(Decimal(str(body["declared_value"])))
        if "signature_required" in body:
            parcel["signature_required"] = bool(body["signature_required"])
        if "hazmat_class" in body:
            parcel["hazmat_class"] = body["hazmat_class"] or "NONE"
        if "destination_address_id" in body:
            parcel["destination_address_id"] = body["destination_address_id"]
        if "time_window_start" in body:
            parcel["time_window_start"] = body["time_window_start"]
        if "time_window_end" in body:
            parcel["time_window_end"] = body["time_window_end"]

        _recompute_parcel_quote(parcel)
        store.stamp_update(parcel)
        return success_object(serialize_parcel(parcel))


@bp.post("/parcels/<pid>/induct-to-hub")
@authed(["SortingHubOperator"])
def induct_to_hub(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if parcel["status"] != "INDUCTED":
            raise_error("ERR_INVALID_STATE", "parcel must be INDUCTED")
        # Hazmat hub certification check
        if parcel.get("hazmat_class", "NONE") != "NONE":
            center = store.transit_centers.get(parcel["origin_center_id"])
            if not center or not center.get("hazmat_certified", False):
                raise_error("ERR_HAZMAT_HUB_NOT_CERTIFIED")
        # Weight precondition
        if float(parcel["weight_kg"]) > 70.0:
            raise_error("ERR_PARCEL_WEIGHT_OUT_OF_RANGE")

        parcel["status"] = "IN_TRANSIT_HUB"
        center = store.transit_centers.get(parcel["origin_center_id"])
        center["parcels_on_belt"] = int(center.get("parcels_on_belt", 0)) + 1
        store.stamp_update(center)
        _recompute_parcel_quote(parcel)
        store.stamp_update(parcel)
        return success_object(serialize_parcel(parcel))


@bp.post("/parcels/<pid>/sort")
@authed(["SortingHubOperator"])
def sort_parcel(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if parcel["status"] != "IN_TRANSIT_HUB":
            raise_error("ERR_INVALID_STATE", "parcel must be IN_TRANSIT_HUB")
        center = store.transit_centers.get(parcel["origin_center_id"])
        if parcel.get("hazmat_class", "NONE") != "NONE":
            if not center or not center.get("hazmat_certified", False):
                raise_error("ERR_HAZMAT_HUB_NOT_CERTIFIED")
        # Postal prefix check
        addr = store.addresses.get(parcel["destination_address_id"])
        if not addr:
            raise_error("ERR_REFERENCE_NOT_FOUND", "destination address missing")
        postal_prefix = addr["postal_code"][:3]
        if postal_prefix not in center.get("serviced_postal_prefixes", []):
            raise_error("ERR_HUB_NOT_SERVICING_POSTAL")

        parcel["status"] = "SORTED"
        center["parcels_on_belt"] = max(0, int(center.get("parcels_on_belt", 0)) - 1)
        store.stamp_update(center)
        store.stamp_update(parcel)
        return success_object(serialize_parcel(parcel))


def _attempts_for_parcel_sorted(parcel_id):
    items = [a for a in store.delivery_attempts.values() if a["parcel_id"] == parcel_id]
    items.sort(key=lambda a: a["attempted_at"])
    return items


def _accepted_appointment_count(parcel_id):
    return sum(
        1
        for a in store.appointments.values()
        if a["parcel_id"] == parcel_id and a["status"] == "ACCEPTED"
    )


def _compute_and_set_final_fee(parcel: dict):
    attempts = _attempts_for_parcel_sorted(parcel["id"])
    accepted = _accepted_appointment_count(parcel["id"])
    parcel["final_fee"] = shipping_fee_final(parcel, attempts, accepted)


@bp.post("/parcels/<pid>/attempts")
@authed(["Driver"])
def record_attempt(user_id, user_role, pid):
    body = get_json_body()
    route_stop_id = require(body, "route_stop_id")
    outcome = require(body, "outcome")
    signature_blob_ref = body.get("signature_blob_ref")
    release_location = body.get("release_location")

    if outcome not in ALL_OUTCOMES:
        raise_error("ERR_REFERENCE_NOT_FOUND", "outcome invalid")

    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        stop = store.route_stops.get(route_stop_id)
        if not stop:
            raise_error("ERR_REFERENCE_NOT_FOUND", "route_stop_id not found")
        if stop["parcel_id"] != pid:
            raise_error("ERR_REFERENCE_NOT_FOUND", "route_stop does not belong to parcel")
        route = store.routes.get(stop["route_id"])
        if not route:
            raise_error("ERR_REFERENCE_NOT_FOUND", "route not found")
        if route["driver_id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        if parcel["status"] != "OUT_FOR_DELIVERY":
            raise_error("ERR_INVALID_STATE", "parcel must be OUT_FOR_DELIVERY")

        # Business-safety checks
        if outcome == "DRIVER_RELEASED":
            customer = store.customers.get(parcel["customer_id"])
            if (
                parcel.get("signature_required", False)
                or parcel.get("hazmat_class", "NONE") != "NONE"
                or not (customer and customer.get("driver_release_authorized", False))
            ):
                raise_error("ERR_DRIVER_RELEASE_NOT_AUTHORIZED")
        if outcome == "DELIVERED_SIGNED":
            if not signature_blob_ref or not isinstance(signature_blob_ref, str) or not signature_blob_ref.strip():
                raise_error("ERR_SIGNATURE_MISSING")

        # Time-window check applies on success attempts.
        if outcome in SUCCESS_OUTCOMES:
            try:
                tw_start = parse_iso8601(parcel["time_window_start"])
                tw_end = parse_iso8601(parcel["time_window_end"])
            except Exception:
                raise_error("ERR_OUTSIDE_TIME_WINDOW")
            now = clock.now()
            if now < tw_start or now > tw_end:
                raise_error("ERR_OUTSIDE_TIME_WINDOW")

        # Create the attempt row first so it's included in chronological iteration.
        from ..clock import iso8601_ms
        attempt = {
            "parcel_id": pid,
            "route_stop_id": route_stop_id,
            "driver_id": user_id,
            "attempted_at": iso8601_ms(clock.now()),
            "outcome": outcome,
            "signature_blob_ref": signature_blob_ref if outcome == "DELIVERED_SIGNED" else None,
            "release_location": release_location if outcome == "DRIVER_RELEASED" else None,
        }
        store.stamp_lightweight_create(attempt)
        store.delivery_attempts[attempt["id"]] = attempt

        parcel["last_attempt_outcome"] = outcome

        if outcome in SUCCESS_OUTCOMES:
            parcel["status"] = "DELIVERED"
            stop["status"] = "COMPLETED"
            _compute_and_set_final_fee(parcel)
        else:
            parcel["status"] = "EXCEPTION"
            stop["status"] = "FAILED"
            parcel["redelivery_attempts"] = int(parcel.get("redelivery_attempts", 0)) + 1

        store.stamp_update(parcel)
        return success_object(serialize_delivery_attempt(attempt), status=201)


@bp.post("/parcels/<pid>/reattempt")
@authed(["Dispatcher"])
def reattempt(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if parcel["status"] != "EXCEPTION":
            raise_error("ERR_INVALID_STATE", "parcel must be EXCEPTION")
        if parcel.get("last_attempt_outcome") == "ADDRESS_INVALID":
            raise_error("ERR_INVALID_STATE", "address invalid blocks reattempt")
        if int(parcel.get("redelivery_attempts", 0)) >= MAX_REDELIVERY_ATTEMPTS:
            raise_error("ERR_REDELIVERY_LIMIT_EXCEEDED")
        customer = store.customers.get(parcel["customer_id"])
        if customer is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "customer missing")
        recompute_customer_rolling(customer)
        if int(customer.get("redelivery_attempts_used_30d", 0)) >= CUSTOMER_REDELIVERY_CAP_30D:
            raise_error("ERR_CUSTOMER_REDELIVERY_CAP_REACHED")

        parcel["status"] = "SORTED"
        # Supersede any PENDING appointment.
        for appt in store.appointments.values():
            if appt["parcel_id"] == pid and appt["status"] == "PENDING":
                appt["status"] = "SUPERSEDED"
                store.stamp_update(appt)
        # Refresh rolling count after the transition.
        recompute_customer_rolling(customer)
        store.stamp_update(parcel)
        store.stamp_update(customer)
        return success_object(serialize_parcel(parcel))


@bp.post("/parcels/<pid>/return-to-sender")
@authed(["Dispatcher"])
def return_to_sender(user_id, user_role, pid):
    with store.lock:
        parcel = store.parcels.get(pid)
        if not parcel:
            raise_error("ERR_NOT_FOUND", "parcel not found")
        if parcel["status"] != "EXCEPTION":
            raise_error("ERR_INVALID_STATE", "parcel must be EXCEPTION")
        attempts_at_cap = int(parcel.get("redelivery_attempts", 0)) >= MAX_REDELIVERY_ATTEMPTS
        addr_invalid = parcel.get("last_attempt_outcome") == "ADDRESS_INVALID"
        if not (attempts_at_cap or addr_invalid):
            raise_error("ERR_INVALID_STATE", "parcel does not yet qualify for return")
        parcel["status"] = "RETURNED_TO_SENDER"
        _compute_and_set_final_fee(parcel)
        store.stamp_update(parcel)
        return success_object(serialize_parcel(parcel))
