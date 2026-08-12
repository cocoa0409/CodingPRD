"""Driver and TrainingRecord endpoints."""

from flask import Blueprint, request

import calc
import errors
import serializers
from db import stamp_new, stamp_new_light, store
from envelope import ok
from listing import page_out
from validators import (
    TRAINING_TYPES,
    as_dt,
    as_enum,
    as_str,
    body,
    endpoint,
    get_or_404,
    req,
)

bp = Blueprint("drivers", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _driver_or_404(driver_id):
    return get_or_404(store.drivers, driver_id, errors.ERR_DRIVER_NOT_FOUND, "Driver")


@bp.route("/hazmat/carriers/<carrierId>/drivers", methods=["POST"])
@endpoint(["CarrierAdmin"])
def create_driver(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    b = body()
    full_name = as_str(req(b, "full_name"), "full_name")
    cdl = as_str(req(b, "cdl_number"), "cdl_number")
    endorsement = as_dt(req(b, "hazmat_endorsement_expires_at"),
                        "hazmat_endorsement_expires_at")
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Carrier must be APPROVED_ACTIVE to onboard drivers")
    for d in store.drivers.values():
        if d["cdl_number"] == cdl:
            raise errors.conflict(errors.ERR_DUPLICATE_CDL,
                                  "cdl_number already registered")
    driver = {
        "carrier_id": carrier["id"],
        "full_name": full_name,
        "cdl_number": cdl,
        "hazmat_endorsement_expires_at": endorsement,
        "status": "ACTIVE",
    }
    stamp_new(driver)
    store.drivers[driver["id"]] = driver
    return ok(serializers.driver(driver), 201)


@bp.route("/hazmat/carriers/<carrierId>/drivers", methods=["GET"])
@endpoint(ALL_ROLES)
def list_drivers(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    rows = [d for d in store.drivers.values() if d["carrier_id"] == carrier["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    posture = request.args.get("qualification_posture")
    if posture is not None:
        rows = [d for d in rows if calc.driver_posture(d) == posture]
    return page_out(rows, serializers.driver)


@bp.route("/hazmat/drivers/<driverId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_driver(uid, role, driverId):
    return ok(serializers.driver(_driver_or_404(driverId)), 200)


@bp.route("/hazmat/drivers/<driverId>/training-records", methods=["POST"])
@endpoint(["CarrierAdmin"])
def create_training_record(uid, role, driverId):
    driver = _driver_or_404(driverId)
    b = body()
    training_type = as_enum(req(b, "training_type"), "training_type", TRAINING_TYPES)
    completed_at = as_dt(req(b, "completed_at"), "completed_at")
    certificate_code = as_str(req(b, "certificate_code"), "certificate_code")
    record = {
        "driver_id": driver["id"],
        "training_type": training_type,
        "completed_at": completed_at,
        "certificate_code": certificate_code,
    }
    stamp_new_light(record)
    record["expires_at"] = calc.training_expiry(
        driver["id"], completed_at, record["_seq"]
    )
    store.training_records[record["id"]] = record
    return ok(serializers.training_record(record), 201)


@bp.route("/hazmat/drivers/<driverId>/training-records", methods=["GET"])
@endpoint(ALL_ROLES)
def list_training_records(uid, role, driverId):
    driver = _driver_or_404(driverId)
    rows = [r for r in store.training_records.values()
            if r["driver_id"] == driver["id"]]
    return page_out(rows, serializers.training_record)
