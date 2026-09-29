"""Thermal events: two independent lifecycles plus the derived join field."""
from flask import Blueprint, request

import calc
import cascade
from common import (API_PREFIX, ApiError, CERT_RANK, R_GATEWAY, R_REG, R_TECH,
                    READ_ROLES_GW, auth, by_created, db, get_body, must, fk,
                    new_record, now, ok, ok_list, opt_str, page, pagination,
                    pack_thermal_events, refresh_technician, req_dt, req_enum,
                    req_int, req_int_list, req_str, touch, vehicle_thermal_events)

bp = Blueprint("thermal", __name__, url_prefix=API_PREFIX)

SEVERITIES = ("S1", "S2", "S3", "S4")
SOURCES = ("TELEMATICS", "SERVICE_CENTER")


def _filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


@bp.route("/thermal-events", methods=["POST"])
def create_event():
    auth((R_TECH, R_GATEWAY))
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    pack_id = req_str(body, "pack_id")
    severity = req_enum(body, "severity", SEVERITIES)
    detected_at = req_dt(body, "detected_at")
    source = req_enum(body, "source", SOURCES)
    positions = req_int_list(body, "affected_module_positions")
    vehicle = must("vehicles", vehicle_id)
    pack = must("packs", pack_id)
    if detected_at > now():
        raise ApiError("ERR_DETECTED_AT_IN_FUTURE", 400,
                       "detected_at must not be later than the logical clock.")
    if vehicle["installed_pack_id"] != pack_id:
        raise ApiError("ERR_PACK_VEHICLE_MISMATCH", 422,
                       "The pack is not the vehicle's installed pack.")
    for existing in vehicle_thermal_events(vehicle_id):
        if existing["event_status"] == "OPEN":
            raise ApiError("ERR_THERMAL_EVENT_OPEN", 409,
                           "The vehicle already carries an open thermal event.")
    deadline = calc.notification_deadline(severity, detected_at)
    record = new_record()
    record.update({
        "vehicle_id": vehicle_id,
        "pack_id": pack_id,
        "severity": severity,
        "detected_at": detected_at,
        "affected_module_positions": list(positions),
        "source": source,
        "containment_status": "DETECTED",
        "notification_status": "PENDING" if deadline is not None else "NOT_REQUIRED",
        "notification_deadline_at": deadline,
        "notification_filed_at": None,
        "regulator_reference": None,
        "reporting_service_center_id": None,
        "containment_steps_completed": 0,
        "event_status": "OPEN",
    })
    db.events[record["id"]] = record
    cascade.derive_event_status(record)
    cascade.thermal_cascade(record, vehicle, pack)
    return ok(record, 201)


@bp.route("/thermal-events/<event_id>", methods=["GET"])
def get_event(event_id):
    auth(READ_ROLES_GW)
    return ok(must("events", event_id))


@bp.route("/thermal-events", methods=["GET"])
def list_events():
    auth(READ_ROLES_GW)
    limit, offset = pagination()
    rows = by_created(list(db.events.values()))
    for field in ("vehicle_id", "pack_id", "severity", "containment_status",
                  "notification_status", "reporting_service_center_id", "event_status",
                  "source"):
        rows = _filter_eq(rows, field, request.args.get(field))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ==================================================== the containment dimension
CONTAINMENT_TARGET = {1: "ISOLATED", 2: "PACK_QUARANTINED", 3: "CONTAINMENT_CLOSED"}


def _origin_center_of_record(pack):
    """The origin center on the pack's most recent shipment, if any."""
    latest = None
    for shipment in by_created(list(db.shipments.values())):
        if shipment["pack_id"] == pack["id"]:
            latest = shipment
    if latest is None:
        return None
    return db.centers.get(latest["origin_service_center_id"])


@bp.route("/thermal-events/<event_id>/containment-step", methods=["POST"])
def containment_step(event_id):
    role, user_id = auth((R_TECH,))
    body = get_body()
    step_index = req_int(body, "step_index", minimum=1)
    opt_str(body, "step_note")
    event = must("events", event_id)
    if step_index != event["containment_steps_completed"] + 1 or step_index > 3:
        raise ApiError("ERR_CONTAINMENT_STEP_OUT_OF_ORDER", 409,
                       "Containment step %s is out of order." % step_index)
    if step_index == 3 and event["notification_status"] not in cascade.SETTLED_NOTIFICATION:
        raise ApiError("ERR_NOTIFICATION_STILL_PENDING", 409,
                       "Containment cannot close while the notification is pending.")
    if step_index == 1:
        technician = db.technicians.get(user_id) if user_id else None
        if technician is not None:
            refresh_technician(technician)
            if technician["status"] == "CERT_LAPSED":
                raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                               "The acting technician's certification has expired.")
            if CERT_RANK[technician["hv_cert_level"]] < CERT_RANK["L2"]:
                raise ApiError("ERR_TECHNICIAN_LEVEL_INSUFFICIENT", 409,
                               "High-voltage isolation demands an L2 or L3 technician.")
    pack = db.packs.get(event["pack_id"])
    event["containment_steps_completed"] = step_index
    event["containment_status"] = CONTAINMENT_TARGET[step_index]
    cascade.derive_event_status(event)
    touch(event)
    if step_index == 2 and pack is not None:
        if pack["status"] == "IN_SERVICE":
            pack["status"] = "QUARANTINED"
            pack["damaged_defective"] = True
            touch(pack)
        center = _origin_center_of_record(pack)
        if center is not None:
            cascade.raise_hazmat_hold(center)
    return ok(event)


# =================================================== the notification dimension
@bp.route("/thermal-events/<event_id>/regulatory-notification", methods=["POST"])
def regulatory_notification(event_id):
    auth((R_REG,))
    body = get_body()
    center_id = req_str(body, "reporting_service_center_id")
    reference = req_str(body, "regulator_reference")
    event = must("events", event_id)
    center = must("centers", center_id)
    if event["notification_status"] != "PENDING":
        raise ApiError("ERR_NOTIFICATION_ALREADY_FILED", 409,
                       "The notification dimension is already settled.")
    filed_at = now()
    event["notification_filed_at"] = filed_at
    event["regulator_reference"] = reference
    event["reporting_service_center_id"] = center_id
    deadline = event["notification_deadline_at"]
    late = deadline is not None and filed_at > deadline
    event["notification_status"] = "LATE_FILED" if late else "FILED"
    cascade.derive_event_status(event)
    touch(event)
    if late:
        center["late_notification_count"] = center["late_notification_count"] + 1
        touch(center)
        cascade.recompute_compliance(center)
    return ok(event)
