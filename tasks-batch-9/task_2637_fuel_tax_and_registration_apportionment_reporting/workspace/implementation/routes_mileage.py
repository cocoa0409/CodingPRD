"""Telematics mileage capture, reconstruction, trip review and fuel evidence."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import serializers as S
from common import (
    ALL_ROLES,
    API_PREFIX,
    DB,
    LIGHT,
    VERSIONED,
    ZERO,
    D,
    authenticate,
    bad_request,
    carrier_scope_guard,
    collection,
    fail,
    find_or_404,
    gallons,
    miles,
    need_enum,
    need_legs,
    need_num,
    need_str,
    new_row,
    ok,
    parse_date,
    parse_instant,
    q_str,
    raw_body,
    reject_unknown,
    touch,
)
from routes_ref import get_carrier_or_404, get_vehicle_or_404

bp = Blueprint("mileage", __name__)


def get_trip_or_404(trip_id):
    return find_or_404(DB.trip_records, trip_id, "ERR_TRIP_RECORD_NOT_FOUND")


def get_purchase_or_404(purchase_id):
    return find_or_404(DB.fuel_purchases, purchase_id, "ERR_FUEL_PURCHASE_NOT_FOUND")


def _insert_legs(trip_id, legs):
    for index, leg in enumerate(legs, start=1):
        row = new_row(LIGHT)
        row.update({
            "trip_record_id": trip_id,
            "jurisdiction_code": leg["jurisdiction_code"],
            "leg_miles": miles(leg["leg_miles"]),
            "leg_sequence": index,
            "leg_status": "ACTIVE",
        })
        DB.mileage_legs[row["id"]] = row


def _void_active_legs(trip_id):
    for leg in calc.trip_legs(trip_id, "ACTIVE"):
        leg["leg_status"] = "VOIDED"


def _check_declared(codes):
    for code in codes:
        if calc.jurisdiction_by_code(code) is None:
            raise fail("ERR_JURISDICTION_NOT_DECLARED",
                       "Jurisdiction %s is not declared." % code)


# --------------------------------------------------------------------------
# Trip capture
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/trip-records")
def create_trip_record():
    authenticate(["CarrierAdmin", "MileageAnalyst"])
    body = raw_body()
    reject_unknown(body, {
        "carrier_id", "vehicle_id", "trip_start_utc", "trip_end_utc",
        "start_odometer", "end_odometer", "legs",
    })

    # Step 4 — body foreign keys, in the pinned body-field order.
    if isinstance(body.get("carrier_id"), str):
        get_carrier_or_404(body["carrier_id"])
    if isinstance(body.get("vehicle_id"), str):
        get_vehicle_or_404(body["vehicle_id"])

    # Step 5 — request shape.
    need_str(body, "carrier_id")
    need_str(body, "vehicle_id")
    start_raw = need_str(body, "trip_start_utc")
    end_raw = need_str(body, "trip_end_utc")
    start_dt = parse_instant(start_raw)
    end_dt = parse_instant(end_raw)
    if start_dt is None:
        raise bad_request("Field 'trip_start_utc' must be an ISO 8601 instant.")
    if end_dt is None:
        raise bad_request("Field 'trip_end_utc' must be an ISO 8601 instant.")
    if end_dt <= start_dt:
        raise bad_request("'trip_end_utc' must be strictly later than 'trip_start_utc'.")
    start_odometer = need_num(body, "start_odometer", minimum=0)
    end_odometer = need_num(body, "end_odometer", minimum=0)
    if end_odometer <= start_odometer:
        raise bad_request("'end_odometer' must be strictly greater than 'start_odometer'.")
    legs = need_legs(body, "legs")
    if not legs:
        raise bad_request("Field 'legs' may not be empty.")

    carrier = get_carrier_or_404(body["carrier_id"])
    vehicle = get_vehicle_or_404(body["vehicle_id"])

    gap = calc.gap_from_previous(vehicle["id"], start_dt, miles(start_odometer))
    if gap < 0:
        raise bad_request(
            "'start_odometer' may not be smaller than the previous trip's 'end_odometer'."
        )

    # Step 6 — jurisdiction declaration.
    _check_declared([leg["jurisdiction_code"] for leg in legs])

    # Step 7 — carrier scope.
    carrier_scope_guard(carrier["id"])

    # Step 24 — half-open interval overlap on the same vehicle.
    for other in calc.vehicle_trips(vehicle["id"]):
        if other["trip_status"] == "REJECTED":
            continue
        if start_dt < other["_end_dt"] and other["_start_dt"] < end_dt:
            raise fail("ERR_TRIP_INTERVAL_OVERLAP",
                       "This interval overlaps an existing trip of the same vehicle.")

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "trip_start_utc": start_raw,
        "trip_end_utc": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "start_odometer": miles(start_odometer),
        "end_odometer": miles(end_odometer),
        "odometer_delta_miles": miles(D(end_odometer) - D(start_odometer)),
        "gap_miles_from_previous": gap,
        "mileage_source": "TELEMATICS",
        "trip_status": "GAP_FLAGGED" if gap > calc.GAP_TOLERANCE_MILES else "CAPTURED",
        "reconstructed_by_user_id": None,
        "supporting_document_reference": None,
        "accepted_leg_miles_total": miles(ZERO),
    })
    DB.trip_records[row["id"]] = row
    _insert_legs(row["id"], legs)
    row["accepted_leg_miles_total"] = calc.active_leg_total(row["id"])

    calc.recompute_carrier_ratio(carrier)
    touch(carrier)
    return ok(S.trip_record_out(row), 201)


@bp.get(API_PREFIX + "/trip-records/<row_id>")
def get_trip_record(row_id):
    authenticate(ALL_ROLES)
    return ok(S.trip_record_out(get_trip_or_404(row_id)))


@bp.get(API_PREFIX + "/trip-records")
def list_trip_records():
    authenticate(ALL_ROLES)
    filters = {
        "carrier_id": q_str("carrier_id"),
        "vehicle_id": q_str("vehicle_id"),
        "trip_status": q_str("trip_status"),
        "mileage_source": q_str("mileage_source"),
    }
    return collection(DB.trip_records.values(), filters,
                      ["_start_dt"], S.trip_record_out)


@bp.get(API_PREFIX + "/trip-records/<row_id>/mileage-legs")
def list_mileage_legs(row_id):
    authenticate(ALL_ROLES)
    trip = get_trip_or_404(row_id)
    rows = [l for l in DB.mileage_legs.values() if l["trip_record_id"] == trip["id"]]
    filters = {"leg_status": q_str("leg_status")}
    return collection(rows, filters, ["leg_sequence"], S.mileage_leg_out)


# --------------------------------------------------------------------------
# Manual reconstruction
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/trip-records/<row_id>/reconstruct")
def reconstruct_trip(row_id):
    authenticate(["MileageAnalyst"])
    trip = get_trip_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"reconstructed_legs", "supporting_document_reference"})

    # Step 5 — shape of what was supplied. An absent or empty legs array and an
    # absent or empty document reference are handled at step 15, not here.
    legs = None
    if body.get("reconstructed_legs") is not None:
        legs = need_legs(body, "reconstructed_legs", required=False)
    reference = body.get("supporting_document_reference")
    if reference is not None and not isinstance(reference, str):
        raise bad_request("Field 'supporting_document_reference' must be a string.")

    # Step 6 — jurisdiction declaration.
    if legs:
        _check_declared([leg["jurisdiction_code"] for leg in legs])

    # Step 9 — state.
    if trip["trip_status"] != "GAP_FLAGGED":
        raise fail("ERR_INVALID_TRIP_STATE",
                   "A trip in %s cannot be reconstructed." % trip["trip_status"])

    # Step 15 — paper trail.
    if not legs or reference is None or reference.strip() == "":
        raise fail("ERR_RECONSTRUCTION_SUPPORT_MISSING",
                   "A reconstruction requires non-empty legs and a document reference.")

    # Steps 16 and 17 — retention first, then the reconstruction window.
    elapsed = DB.clock.now() - trip["_end_dt"]
    if elapsed > timedelta(days=calc.RECORD_RETENTION_DAYS):
        raise fail("ERR_RETENTION_PERIOD_EXPIRED",
                   "The record retention period for this trip has expired.")
    if elapsed > timedelta(days=calc.RECONSTRUCTION_WINDOW_DAYS):
        raise fail("ERR_RECONSTRUCTION_WINDOW_CLOSED",
                   "The manual reconstruction window for this trip has closed.")

    # Step 26 — reconciliation against the odometer evidence.
    submitted = miles(sum((leg["leg_miles"] for leg in legs), ZERO))
    expected = miles(trip["odometer_delta_miles"] + trip["gap_miles_from_previous"])
    if abs(submitted - expected) > calc.LEG_MILEAGE_TOLERANCE_MILES:
        raise fail("ERR_LEG_MILEAGE_MISMATCH",
                   "Reconstructed legs total %s but the odometer evidence is %s."
                   % (submitted, expected))

    _void_active_legs(trip["id"])
    _insert_legs(trip["id"], legs)
    trip["trip_status"] = "RECONSTRUCTED"
    trip["mileage_source"] = "MANUAL_RECONSTRUCTION"
    trip["reconstructed_by_user_id"] = g.user_id
    trip["supporting_document_reference"] = reference
    trip["accepted_leg_miles_total"] = calc.active_leg_total(trip["id"])
    touch(trip)

    carrier = DB.carriers.get(trip["carrier_id"])
    if carrier is not None:
        calc.recompute_carrier_ratio(carrier)
        touch(carrier)
    return ok(S.trip_record_out(trip))


# --------------------------------------------------------------------------
# Trip review
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/trip-records/<row_id>/review")
def review_trip(row_id):
    authenticate(["ComplianceOfficer"])
    trip = get_trip_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"decision", "review_note"})
    decision = need_enum(body, "decision", ("ACCEPT", "REJECT"))
    need_str(body, "review_note", required=False)

    status = trip["trip_status"]
    vehicle = DB.vehicles.get(trip["vehicle_id"])

    # Step 9 — does the requested transition exist at all?
    target = None
    if decision == "ACCEPT":
        if status == "CAPTURED":
            if trip["gap_miles_from_previous"] > calc.GAP_TOLERANCE_MILES:
                raise fail("ERR_INVALID_TRIP_STATE",
                           "A gap beyond tolerance must be reconstructed first.")
            if vehicle is not None and vehicle["vehicle_status"] == "TRANSFERRED":
                raise fail("ERR_INVALID_TRIP_STATE",
                           "A transferred unit cannot admit new distance.")
            target = "ACCEPTED"
        elif status == "RECONSTRUCTED":
            target = "ACCEPTED"
    else:
        if status in ("CAPTURED", "GAP_FLAGGED"):
            target = "REJECTED"
        elif status == "RECONSTRUCTED":
            target = "GAP_FLAGGED"
    if target is None:
        raise fail("ERR_INVALID_TRIP_STATE",
                   "No %s transition exists from %s." % (decision, status))

    # Step 18 — segregation of duties, only where an identity was recorded.
    if (trip["reconstructed_by_user_id"] is not None
            and trip["reconstructed_by_user_id"] == g.user_id):
        raise fail("ERR_SEGREGATION_OF_DUTIES",
                   "The analyst who reconstructed this trip may not review it.")

    if status == "RECONSTRUCTED" and decision == "ACCEPT":
        if not trip["supporting_document_reference"]:
            raise fail("ERR_RECONSTRUCTION_SUPPORT_MISSING",
                       "The reconstruction's supporting document reference is missing.")

    if target == "ACCEPTED":
        trip["trip_status"] = "ACCEPTED"
        trip["accepted_leg_miles_total"] = calc.active_leg_total(trip["id"])
    elif target == "REJECTED":
        _void_active_legs(trip["id"])
        trip["trip_status"] = "REJECTED"
        trip["accepted_leg_miles_total"] = miles(ZERO)
    else:
        _void_active_legs(trip["id"])
        trip["trip_status"] = "GAP_FLAGGED"
        trip["accepted_leg_miles_total"] = miles(ZERO)
        trip["supporting_document_reference"] = None
        trip["reconstructed_by_user_id"] = None
    touch(trip)

    carrier = DB.carriers.get(trip["carrier_id"])
    if carrier is not None:
        calc.recompute_carrier_ratio(carrier)
        touch(carrier)
    return ok(S.trip_record_out(trip))


# --------------------------------------------------------------------------
# Fuel purchases
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/fuel-purchases")
def create_fuel_purchase():
    authenticate(["CarrierAdmin", "MileageAnalyst"])
    body = raw_body()
    reject_unknown(body, {
        "carrier_id", "vehicle_id", "jurisdiction_code", "purchase_date",
        "gallons", "tax_paid_flag", "receipt_reference",
    })

    if isinstance(body.get("carrier_id"), str):
        get_carrier_or_404(body["carrier_id"])
    if isinstance(body.get("vehicle_id"), str):
        get_vehicle_or_404(body["vehicle_id"])

    need_str(body, "carrier_id")
    need_str(body, "vehicle_id")
    code = need_str(body, "jurisdiction_code")
    purchase_date = need_str(body, "purchase_date")
    day = parse_date(purchase_date)
    if day is None:
        raise bad_request("Field 'purchase_date' must be a YYYY-MM-DD date.")
    amount = need_num(body, "gallons", minimum_exclusive=0)
    tax_paid_flag = body.get("tax_paid_flag")
    if tax_paid_flag is None:
        tax_paid_flag = True
    elif not isinstance(tax_paid_flag, bool):
        raise bad_request("Field 'tax_paid_flag' must be a boolean.")
    receipt = body.get("receipt_reference")
    if receipt is not None and not isinstance(receipt, str):
        raise bad_request("Field 'receipt_reference' must be a string.")

    carrier = get_carrier_or_404(body["carrier_id"])
    vehicle = get_vehicle_or_404(body["vehicle_id"])

    if calc.jurisdiction_by_code(code) is None:
        raise fail("ERR_JURISDICTION_NOT_DECLARED",
                   "Jurisdiction %s is not declared." % code)

    carrier_scope_guard(carrier["id"])

    accepted = bool(receipt is not None and receipt.strip() != "" and tax_paid_flag)

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "jurisdiction_code": code,
        "purchase_date": purchase_date,
        "_purchase_day": day,
        "gallons": gallons(amount),
        "tax_paid_flag": tax_paid_flag,
        "receipt_reference": receipt,
        "purchase_status": "ACCEPTED" if accepted else "RECORDED",
        "disallow_reason_code": None,
    })
    DB.fuel_purchases[row["id"]] = row

    if accepted:
        carrier["tax_paid_gallons_ytd"] = gallons(
            carrier["tax_paid_gallons_ytd"] + row["gallons"]
        )
        touch(carrier)
    return ok(S.fuel_purchase_out(row), 201)


@bp.get(API_PREFIX + "/fuel-purchases/<row_id>")
def get_fuel_purchase(row_id):
    authenticate(ALL_ROLES)
    return ok(S.fuel_purchase_out(get_purchase_or_404(row_id)))


@bp.get(API_PREFIX + "/fuel-purchases")
def list_fuel_purchases():
    authenticate(ALL_ROLES)
    filters = {
        "carrier_id": q_str("carrier_id"),
        "vehicle_id": q_str("vehicle_id"),
        "jurisdiction_code": q_str("jurisdiction_code"),
        "purchase_status": q_str("purchase_status"),
    }
    return collection(DB.fuel_purchases.values(), filters,
                      ["purchase_date"], S.fuel_purchase_out)


@bp.post(API_PREFIX + "/fuel-purchases/<row_id>/disallow")
def disallow_fuel_purchase(row_id):
    authenticate(["MileageAnalyst"])
    purchase = get_purchase_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"disallow_reason_code"})
    reason = need_enum(body, "disallow_reason_code",
                       ("MISSING_RECEIPT", "BULK_UNTAXED", "DUPLICATE",
                        "AUDIT_ADJUSTMENT"))

    # Step 9 — state.
    if purchase["purchase_status"] == "DISALLOWED":
        raise fail("ERR_INVALID_PURCHASE_STATE",
                   "This purchase is already disallowed.")

    # Step 22 — the filed quarter's fuel basis is frozen.
    for ret in DB.fuel_tax_returns.values():
        if ret["carrier_id"] != purchase["carrier_id"]:
            continue
        if ret["return_status"] not in ("FILED", "AUDIT_ADJUSTED"):
            continue
        start, end = calc.quarter_date_window(ret["filing_year"], ret["filing_quarter"])
        if start <= purchase["_purchase_day"] < end:
            raise fail("ERR_PURCHASE_LOCKED_BY_FILED_RETURN",
                       "A filed return covers this purchase date.")

    was_accepted = purchase["purchase_status"] == "ACCEPTED"
    purchase["purchase_status"] = "DISALLOWED"
    purchase["disallow_reason_code"] = reason
    touch(purchase)

    carrier = DB.carriers.get(purchase["carrier_id"])
    if carrier is not None:
        if was_accepted:
            carrier["tax_paid_gallons_ytd"] = gallons(
                carrier["tax_paid_gallons_ytd"] - purchase["gallons"]
            )
        touch(carrier)
    return ok(S.fuel_purchase_out(purchase))
