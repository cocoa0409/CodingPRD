"""Registry endpoints: patients, physicians, technicians, devices."""
from datetime import datetime

import db
from bp import bp
from db import base_record
from domain import serialize_technician
from errors import ApiError
from helpers import (READ_ROLES, auth, body, opt_bool, opt_enum, pagination,
                     req_enum, req_int, req_str, require, sorted_by_creation)
from response import serialize, success, success_list

INSURANCE_PLANS = {"MEDICARE", "COMMERCIAL", "SELF_PAY"}
CERT_LEVELS = {"CCT", "CRAT", "RN"}
NOTIF_PREFS = {"PHONE", "PORTAL"}
DEVICE_MODELS = {"HOLTER", "EVENT", "IMPLANTABLE"}
DEVICE_STATUSES = {"IN_STOCK", "RESERVED", "DEPLOYED", "RETURN_IN_TRANSIT",
                   "REFURBISHING", "LOST"}


# ------------------------------------------------------------------ patients
@bp.post("/v1/patients")
def create_patient():
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    d = body()
    full_name = req_str(d, "full_name")
    dob = req_str(d, "date_of_birth")
    mrn = req_str(d, "mrn")
    phone = req_str(d, "phone")
    plan = req_enum(d, "insurance_plan", INSURANCE_PLANS)
    try:
        datetime.strptime(dob, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "date_of_birth must be YYYY-MM-DD")
    if any(p["mrn"] == mrn for p in db.patients.values()):
        raise ApiError("ERR_DUPLICATE_MRN", 409, "mrn already registered")
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "mrn": mrn,
        "phone": phone,
        "insurance_plan": plan,
        "open_compliance_events": 0,
    })
    db.patients[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/patients/<patient_id>")
def get_patient(patient_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.patients.get(patient_id)
    if rec is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", 404, "Patient not found")
    return success(serialize(rec))


# ----------------------------------------------------------------- physicians
@bp.post("/v1/physicians")
def create_physician():
    uid, role = auth()
    require(role, {"PlatformAdmin"})
    d = body()
    full_name = req_str(d, "full_name")
    npi = req_str(d, "npi")
    specialty = req_str(d, "specialty")
    pref = opt_enum(d, "notification_preference", NOTIF_PREFS, default="PORTAL")
    if not (isinstance(npi, str) and len(npi) == 10 and npi.isdigit()):
        raise ApiError("ERR_VALIDATION", 400, "npi must be exactly 10 digits")
    if any(p["npi"] == npi for p in db.physicians.values()):
        raise ApiError("ERR_DUPLICATE_NPI", 409, "npi already registered")
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
        "notification_preference": pref,
    })
    db.physicians[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/physicians/<physician_id>")
def get_physician(physician_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.physicians.get(physician_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Physician not found")
    return success(serialize(rec))


# ---------------------------------------------------------------- technicians
@bp.post("/v1/technicians")
def create_technician():
    uid, role = auth()
    require(role, {"PlatformAdmin"})
    d = body()
    full_name = req_str(d, "full_name")
    cert = req_enum(d, "certification_level", CERT_LEVELS)
    capacity = req_int(d, "shift_capacity", lo=1)
    on_shift = opt_bool(d, "on_shift", default=True)
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "certification_level": cert,
        "shift_capacity": capacity,
        "on_shift": on_shift,
        "open_alert_load": 0,
        "alerts_acknowledged_total": 0,
    })
    db.technicians[rec["id"]] = rec
    return success(serialize_technician(rec), 201)


@bp.get("/v1/technicians/<technician_id>")
def get_technician(technician_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.technicians.get(technician_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Technician not found")
    return success(serialize_technician(rec))


# -------------------------------------------------------------------- devices
@bp.post("/v1/devices")
def create_device():
    uid, role = auth()
    require(role, {"InventoryManager"})
    d = body()
    serial = req_str(d, "serial_number")
    model = req_enum(d, "model", DEVICE_MODELS)
    if any(x["serial_number"] == serial for x in db.devices.values()):
        raise ApiError("ERR_DUPLICATE_SERIAL", 409, "serial_number already registered")
    rec = base_record()
    rec.update({
        "serial_number": serial,
        "model": model,
        "status": "IN_STOCK",
        "refurbishment_due_at": None,
    })
    db.devices[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/devices/<device_id>")
def get_device(device_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.devices.get(device_id)
    if rec is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", 404, "Device not found")
    return success(serialize(rec))


@bp.get("/v1/devices")
def list_devices():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    status_f = request.args.get("status")
    model_f = request.args.get("model")
    items = list(db.devices.values())
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    if model_f is not None:
        items = [x for x in items if x["model"] == model_f]
    return success_list(sorted_by_creation(items), limit, offset)
