"""Prescription intake and the verification state machine (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import serializers as S
import services
from auth import acting_user_id, require_roles
from envelope import created, listing, ok
from errors import ApiError
from store import db, now, sorted_rows, stamp_common, touch
from validate import F, json_body, parse_date, validate_body

bp = Blueprint("prescriptions", __name__)

QUARTER = Decimal("0.25")


def _multiple_of_quarter(value):
    return (calc.D(value) / QUARTER) % 1 == 0


def _check_powers(data):
    for key in ("sphere_od", "sphere_os"):
        v = calc.D(data[key])
        if v < Decimal("-20.00") or v > Decimal("20.00") or not _multiple_of_quarter(v):
            raise ApiError("ERR_RX_POWER_OUT_OF_RANGE")
    for key in ("cylinder_od", "cylinder_os"):
        v = calc.D(data[key])
        if v < Decimal("-6.00") or v > Decimal("0.00") or not _multiple_of_quarter(v):
            raise ApiError("ERR_RX_POWER_OUT_OF_RANGE")
    for key in ("axis_od", "axis_os"):
        if data[key] is None:
            continue
        if int(data[key]) < 1 or int(data[key]) > 180:
            raise ApiError("ERR_RX_POWER_OUT_OF_RANGE")
    if data["add_power"] is not None:
        v = calc.D(data["add_power"])
        if v < Decimal("0.75") or v > Decimal("3.50") or not _multiple_of_quarter(v):
            raise ApiError("ERR_RX_POWER_OUT_OF_RANGE")
    for key in ("prism_od", "prism_os"):
        if data[key] is None:
            continue
        v = calc.D(data[key])
        if v < Decimal("0.00") or v > Decimal("5.00") or not _multiple_of_quarter(v):
            raise ApiError("ERR_RX_POWER_OUT_OF_RANGE")


def _set_expiry(rx, prescriber):
    issued = parse_date(rx["issued_on"])
    rx["expires_at"] = calc.expiration_instant(issued, prescriber["max_rx_validity_months"])


@bp.post("/prescriptions")
def create_prescription():
    body = json_body()
    data = validate_body(
        body,
        [
            F("patient_id", "string"),
            F("prescriber_id", "string"),
            F("prescriber_npi_claimed", "string", pattern=r"^\d{10}$"),
            F("prescriber_license_state_claimed", "string", pattern=r"^[A-Z]{2}$"),
            F("sphere_od", "number"),
            F("cylinder_od", "number"),
            F("axis_od", "int", required=False),
            F("sphere_os", "number"),
            F("cylinder_os", "number"),
            F("axis_os", "int", required=False),
            F("add_power", "number", required=False),
            F("prism_od", "number", required=False),
            F("prism_os", "number", required=False),
            F("pd_distance_mm", "number"),
            F("issued_on", "date"),
        ],
    )
    services.get_or_404(db.patients, data["patient_id"], "ERR_PATIENT_NOT_FOUND")
    prescriber = services.get_or_404(db.prescribers, data["prescriber_id"], "ERR_PRESCRIBER_NOT_FOUND")
    require_roles("StoreOptician")

    _check_powers(data)

    for cyl, axis in (("cylinder_od", "axis_od"), ("cylinder_os", "axis_os")):
        if calc.D(data[cyl]) != 0 and data[axis] is None:
            raise ApiError("ERR_RX_AXIS_REQUIRED")

    issued = parse_date(data["issued_on"])
    if issued > now().date():
        raise ApiError("ERR_RX_ISSUE_DATE_IN_FUTURE")

    pd = calc.D(data["pd_distance_mm"])
    if pd < Decimal("40.0") or pd > Decimal("80.0"):
        raise ApiError("ERR_PD_OUT_OF_RANGE")

    add_power = data["add_power"]
    row = stamp_common(
        {
            "prescriber_id": data["prescriber_id"],
            "patient_id": data["patient_id"],
            "prescriber_npi_claimed": data["prescriber_npi_claimed"],
            "prescriber_license_state_claimed": data["prescriber_license_state_claimed"],
            "sphere_od": data["sphere_od"],
            "sphere_os": data["sphere_os"],
            "cylinder_od": data["cylinder_od"],
            "cylinder_os": data["cylinder_os"],
            "axis_od": data["axis_od"],
            "axis_os": data["axis_os"],
            "add_power_od": add_power,
            "add_power_os": add_power,
            "prism_diopter_od": data["prism_od"] if data["prism_od"] is not None else 0.00,
            "prism_diopter_os": data["prism_os"] if data["prism_os"] is not None else 0.00,
            "pd_distance_mm": data["pd_distance_mm"],
            "issued_on": data["issued_on"],
            "verification_status": "UNVERIFIED",
            "verification_note": None,
            "verified_at": None,
            "requires_multifocal": calc.D(add_power) > 0 if add_power is not None else False,
            "resubmit_count": 0,
        }
    )
    _set_expiry(row, prescriber)
    db.prescriptions[row["id"]] = row
    return created(S.prescription(row))


@bp.get("/prescriptions/<rid>")
def get_prescription(rid):
    row = services.get_or_404(db.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    require_roles()
    return ok(S.prescription(row))


@bp.get("/prescriptions")
def list_prescriptions():
    require_roles()
    rows = sorted_rows(db.prescriptions)
    for arg, field in (("prescriber_id", "prescriber_id"), ("patient_id", "patient_id"),
                       ("verification_status", "verification_status")):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, S.prescription)


@bp.post("/prescriptions/<rid>/verify")
def verify_prescription(rid):
    body = json_body()
    data = validate_body(body, [F("verification_note", "string", required=False)])
    rx = services.get_or_404(db.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    require_roles("StoreOptician")
    if rx["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_RX_STATE_INVALID")
    prescriber = db.prescribers.get(rx["prescriber_id"])
    if prescriber is None or prescriber["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIBER_NOT_ACTIVE")
    if (rx["prescriber_npi_claimed"] != prescriber["npi"]
            or rx["prescriber_license_state_claimed"] != prescriber["license_state"]):
        raise ApiError("ERR_PRESCRIBER_RECORD_MISMATCH")
    rx["verification_status"] = "VERIFIED"
    rx["verified_at"] = now()
    if data["verification_note"] is not None:
        rx["verification_note"] = data["verification_note"]
    touch(rx)
    return ok(S.prescription(rx))


@bp.post("/prescriptions/<rid>/prescriber-attest")
def attest_prescription(rid):
    body = json_body()
    data = validate_body(body, [F("attestation_statement", "string")])
    rx = services.get_or_404(db.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    require_roles("Prescriber")
    if rx["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_RX_STATE_INVALID")
    if acting_user_id() != rx["prescriber_id"]:
        raise ApiError("ERR_NOT_PRESCRIBER_OF_RECORD")
    prescriber = db.prescribers.get(rx["prescriber_id"])
    if prescriber is None or prescriber["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIBER_NOT_ACTIVE")
    rx["verification_status"] = "VERIFIED"
    rx["verified_at"] = now()
    rx["verification_note"] = data["attestation_statement"]
    touch(rx)
    return ok(S.prescription(rx))


@bp.post("/prescriptions/<rid>/reject")
def reject_prescription(rid):
    body = json_body()
    data = validate_body(body, [F("verification_note", "string")])
    rx = services.get_or_404(db.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    require_roles("StoreOptician")
    if rx["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
        raise ApiError("ERR_RX_STATE_INVALID")
    rx["verification_status"] = "REJECTED"
    rx["verification_note"] = data["verification_note"]
    rx["verified_at"] = None
    touch(rx)
    return ok(S.prescription(rx))


@bp.post("/prescriptions/<rid>/resubmit")
def resubmit_prescription(rid):
    body = json_body()
    data = validate_body(
        body,
        [
            F("corrected_issued_on", "date", required=False),
            F("corrected_pd_distance_mm", "number", required=False),
        ],
    )
    rx = services.get_or_404(db.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    require_roles("StoreOptician")
    if rx["verification_status"] != "REJECTED":
        raise ApiError("ERR_RX_STATE_INVALID")
    rx["verification_status"] = "UNVERIFIED"
    rx["verification_note"] = None
    rx["resubmit_count"] += 1
    if data["corrected_pd_distance_mm"] is not None:
        rx["pd_distance_mm"] = data["corrected_pd_distance_mm"]
    if data["corrected_issued_on"] is not None:
        rx["issued_on"] = data["corrected_issued_on"]
        prescriber = db.prescribers.get(rx["prescriber_id"])
        if prescriber is not None:
            _set_expiry(rx, prescriber)
    touch(rx)
    return ok(S.prescription(rx))
