"""Monitoring orders and enrollments."""
from datetime import timedelta

import db
from bp import bp
from clock import now
from db import base_record, touch
from errors import ApiError
from helpers import (READ_ROLES, auth, body, opt_enum, pagination, req_enum,
                     req_int, req_str, require, sorted_by_creation)
from response import serialize, success, success_list

MONITOR_TYPES = {"HOLTER", "EVENT", "IMPLANTABLE"}
EDUCATION_METHODS = {"IN_PERSON", "PHONE", "VIDEO"}
ORDER_STATUSES = {"OPEN", "IN_SERVICE", "FULFILLED", "CANCELLED"}
NON_TERMINAL_ENROLLMENT = {"INITIATED", "EDUCATED", "ACTIVATION_FAILED"}
DEVICE_COMMITTED = {"RESERVED", "DEPLOYED", "RETURN_IN_TRANSIT", "LOST"}


# --------------------------------------------------------------------- orders
@bp.post("/v1/monitoring-orders")
def create_order():
    uid, role = auth()
    require(role, {"Physician"})
    d = body()
    patient_id = d.get("patient_id")
    if patient_id is not None and patient_id not in db.patients:
        raise ApiError("ERR_PATIENT_NOT_FOUND", 404, "Patient not found")
    patient_id = req_str(d, "patient_id")
    monitor_type = req_enum(d, "monitor_type", MONITOR_TYPES)
    prescribed_days = req_int(d, "prescribed_days", lo=5, hi=45)
    indication_codes = d.get("indication_codes")
    if indication_codes is None:
        indication_codes = []
    if not isinstance(indication_codes, list):
        raise ApiError("ERR_VALIDATION", 400, "indication_codes must be a list")
    rec = base_record()
    rec.update({
        "patient_id": patient_id,
        "ordering_physician_id": uid,
        "monitor_type": monitor_type,
        "prescribed_days": prescribed_days,
        "indication_codes": list(indication_codes),
        "status": "OPEN",
    })
    db.orders[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/monitoring-orders/<order_id>")
def get_order(order_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.orders.get(order_id)
    if rec is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    return success(serialize(rec))


@bp.get("/v1/monitoring-orders")
def list_orders():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    patient_f = request.args.get("patient_id")
    physician_f = request.args.get("ordering_physician_id")
    status_f = request.args.get("status")
    items = list(db.orders.values())
    if patient_f is not None:
        items = [x for x in items if x["patient_id"] == patient_f]
    if physician_f is not None:
        items = [x for x in items if x["ordering_physician_id"] == physician_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.post("/v1/monitoring-orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role = auth()
    require(role, {"Physician"})
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    if order["ordering_physician_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Caller is not the ordering physician")
    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only OPEN orders can be cancelled")
    for e in db.enrollments.values():
        if e["order_id"] == order["id"] and e["status"] in NON_TERMINAL_ENROLLMENT:
            e["status"] = "ABORTED"
            touch(e)
            dev = db.devices.get(e["device_id"])
            if dev is not None and dev["status"] == "RESERVED":
                dev["status"] = "IN_STOCK"
                touch(dev)
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


# --------------------------------------------------------------- enrollments
def _reserve_device_or_raise(device, order):
    """Shared reservation vetting for enrollment create and retry."""
    if device["status"] in DEVICE_COMMITTED:
        raise ApiError("ERR_DEVICE_NOT_IN_STOCK", 409,
                       "Device is not available for reservation")
    if (device["status"] == "REFURBISHING"
            and device["refurbishment_due_at"] is not None
            and device["refurbishment_due_at"] > now()):
        raise ApiError("ERR_DEVICE_NOT_REFURBISHED", 409,
                       "Refurbishment buffer has not elapsed")
    if device["model"] != order["monitor_type"]:
        raise ApiError("ERR_DEVICE_CATEGORY_MISMATCH", 422,
                       "device.model must equal order.monitor_type")


@bp.post("/v1/monitoring-orders/<order_id>/enrollments")
def create_enrollment(order_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    d = body()
    device_id = d.get("device_id")
    if device_id is not None and device_id not in db.devices:
        raise ApiError("ERR_DEVICE_NOT_FOUND", 404, "Device not found")
    device_id = req_str(d, "device_id")
    expected_version = req_int(d, "expected_order_version")
    device = db.devices[device_id]
    # state rung: committed device, then OCC on order version
    if device["status"] in DEVICE_COMMITTED:
        raise ApiError("ERR_DEVICE_NOT_IN_STOCK", 409,
                       "Device is not available for reservation")
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_order_version does not match current order version")
    # temporal rung: refurbishment buffer
    if (device["status"] == "REFURBISHING"
            and device["refurbishment_due_at"] is not None
            and device["refurbishment_due_at"] > now()):
        raise ApiError("ERR_DEVICE_NOT_REFURBISHED", 409,
                       "Refurbishment buffer has not elapsed")
    # constraint rung: category match
    if device["model"] != order["monitor_type"]:
        raise ApiError("ERR_DEVICE_CATEGORY_MISMATCH", 422,
                       "device.model must equal order.monitor_type")
    # supersede prior non-terminal enrollments of this order
    for e in db.enrollments.values():
        if e["order_id"] == order["id"] and e["status"] in NON_TERMINAL_ENROLLMENT:
            e["status"] = "ABORTED"
            touch(e)
            dev = db.devices.get(e["device_id"])
            if dev is not None and dev["status"] == "RESERVED":
                dev["status"] = "IN_STOCK"
                touch(dev)
    device["status"] = "RESERVED"
    touch(device)
    touch(order)  # order.version += 1
    rec = base_record()
    rec.update({
        "order_id": order["id"],
        "device_id": device["id"],
        "education_completed": False,
        "education_method": None,
        "status": "INITIATED",
        "attempts_count": 0,
        "episode_id": None,
    })
    db.enrollments[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/enrollments")
def list_enrollments():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    order_f = request.args.get("order_id")
    device_f = request.args.get("device_id")
    episode_f = request.args.get("episode_id")
    status_f = request.args.get("status")
    items = list(db.enrollments.values())
    if order_f is not None:
        items = [x for x in items if x["order_id"] == order_f]
    if device_f is not None:
        items = [x for x in items if x["device_id"] == device_f]
    if episode_f is not None:
        items = [x for x in items if x["episode_id"] == episode_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.get("/v1/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    uid, role = auth()
    require(role, READ_ROLES)
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Enrollment not found")
    return success(serialize(rec))


@bp.post("/v1/enrollments/<enrollment_id>/complete-education")
def complete_education(enrollment_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Enrollment not found")
    d = body()
    method = req_enum(d, "education_method", EDUCATION_METHODS)
    if rec["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Education can only be recorded on an INITIATED enrollment")
    rec["status"] = "EDUCATED"
    rec["education_completed"] = True
    rec["education_method"] = method
    touch(rec)
    return success(serialize(rec))


@bp.post("/v1/enrollments/<enrollment_id>/activate")
def activate_enrollment(enrollment_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Enrollment not found")
    d = body()
    baseline = req_int(d, "baseline_signal_quality", lo=0, hi=100)
    if rec["status"] != "EDUCATED":
        raise ApiError("ERR_EDUCATION_INCOMPLETE", 422,
                       "Enrollment must be EDUCATED before activation")
    device = db.devices.get(rec["device_id"])
    if device is None or device["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Reserved device is no longer held for this enrollment")
    order = db.orders.get(rec["order_id"])
    # temporal rung: one live episode per patient
    for ep in db.episodes.values():
        if ep["patient_id"] == order["patient_id"] and ep["clinical_status"] == "MONITORING":
            raise ApiError("ERR_ACTIVE_EPISODE_EXISTS", 409,
                           "Patient already has an episode in MONITORING")
    t = now()
    if baseline >= 40:
        ep = base_record()
        ep.update({
            "enrollment_id": rec["id"],
            "patient_id": order["patient_id"],
            "monitor_type": order["monitor_type"],
            "started_at": t,
            "scheduled_end_at": t + timedelta(days=order["prescribed_days"]),
            "completed_at": None,
            "clinical_status": "MONITORING",
            "compliance_status": "COMPLIANT",
            "strike_count": 0,
            "transmission_count": 0,
            "unacknowledged_critical_count": 0,
            "total_billed_cents": 0,
        })
        db.episodes[ep["id"]] = ep
        rec["status"] = "ACTIVATED"
        rec["episode_id"] = ep["id"]
        touch(rec)
        device["status"] = "DEPLOYED"
        touch(device)
        if order["status"] == "OPEN":
            order["status"] = "IN_SERVICE"
            touch(order)
    else:
        device["status"] = "REFURBISHING"
        device["refurbishment_due_at"] = t + timedelta(hours=48)
        touch(device)
        rec["status"] = "ACTIVATION_FAILED"
        rec["attempts_count"] += 1
        touch(rec)
    return success(serialize(rec))


@bp.post("/v1/enrollments/<enrollment_id>/retry")
def retry_enrollment(enrollment_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Enrollment not found")
    d = body()
    device_id = d.get("device_id")
    if device_id is not None and device_id not in db.devices:
        raise ApiError("ERR_DEVICE_NOT_FOUND", 404, "Device not found")
    device_id = req_str(d, "device_id")
    device = db.devices[device_id]
    if rec["status"] != "ACTIVATION_FAILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only ACTIVATION_FAILED enrollments can be retried")
    _reserve_device_or_raise(device, db.orders[rec["order_id"]])
    device["status"] = "RESERVED"
    touch(device)
    rec["device_id"] = device["id"]
    rec["status"] = "INITIATED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/v1/enrollments/<enrollment_id>/abort")
def abort_enrollment(enrollment_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Enrollment not found")
    if rec["status"] not in NON_TERMINAL_ENROLLMENT:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only non-terminal enrollments can be aborted")
    rec["status"] = "ABORTED"
    touch(rec)
    dev = db.devices.get(rec["device_id"])
    if dev is not None and dev["status"] == "RESERVED":
        dev["status"] = "IN_STOCK"
        touch(dev)
    return success(serialize(rec))
