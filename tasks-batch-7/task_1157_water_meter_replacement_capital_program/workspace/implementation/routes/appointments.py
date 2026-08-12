"""Appointment endpoints (PRD 3.4): booking with notice window / crew bucket,
confirm, complete, no-access strike cascade, customer cancel."""
from datetime import timedelta

import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import (
    ALL_ROLES,
    check_contractor_ownership,
    require_roles,
)
from response import ok_object
from services.core import (
    NO_ACCESS_STRIKE_THRESHOLD,
    get_or_404,
    list_page,
    ser_appointment,
)
from flask import Blueprint, request
from validate import body, req_date, req_enum, req_int, req_str

bp = Blueprint("appointments", __name__)

WINDOWS = ("AM", "PM", "EVE")
BOOKABLE_STATES = ("NOTIFIED", "SCHEDULED", "ACCESS_FAILED")


@bp.post("/api/appointments")
@require_roles("Scheduler")
def book_appointment():
    b = body()
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    wo = get_or_404(db.work_orders, work_order_id, "WorkOrder")
    slot_date = req_date(b, "slot_date")
    window = req_enum(b, "window", WINDOWS)
    expected_version = req_int(b, "expected_work_order_version")
    # State (stage 7).
    if wo["lifecycle_status"] not in BOOKABLE_STATES:
        raise_err("ERR_INVALID_STATE",
                  "Work order is not in a bookable state")
    if wo["hold_status"] != "CLEAR":
        raise_err("ERR_INVALID_STATE", "Work order is ON_HOLD")
    # OCC on the work order (PRD 2.5).
    if expected_version != wo["version"]:
        raise_err("ERR_STALE_WORK_ORDER_VERSION",
                  "expected_work_order_version does not match current version")
    account = get_or_404(db.accounts, wo["service_account_id"], "ServiceAccount")
    wave = get_or_404(db.waves, wo["wave_id"], "Wave")
    program = get_or_404(db.programs, wave["program_id"], "Program")
    # Qualifying deliveries: CRITICAL accounts count CERTIFIED_MAIL only;
    # other tiers count every DELIVERED notification (PRD 3.4).
    qualifying = []
    has_delivered_certified = False
    for n in db.notifications.values():
        if n["work_order_id"] != wo["id"] or n["status"] != "DELIVERED":
            continue
        if n["channel"] == "CERTIFIED_MAIL":
            has_delivered_certified = True
        if account["priority_tier"] != "CRITICAL" or n["channel"] == "CERTIFIED_MAIL":
            if n["delivered_at"] is not None:
                qualifying.append(n)
    # Safety (stage 9): CRITICAL accounts require a DELIVERED CERTIFIED_MAIL.
    if account["priority_tier"] == "CRITICAL" and not has_delivered_certified:
        raise_err("ERR_CRITICAL_CHANNEL_REQUIRED",
                  "CRITICAL account requires a DELIVERED CERTIFIED_MAIL notification")
    # Temporal (stage 10): notice window from the latest qualifying delivery.
    if not qualifying:
        raise_err("ERR_NOTICE_WINDOW_NOT_MET",
                  "No qualifying DELIVERED notification")
    latest_delivered = max(n["delivered_at"] for n in qualifying)
    eligible_from = latest_delivered.date() + timedelta(days=program["notice_days"])
    if slot_date < eligible_from:
        raise_err("ERR_NOTICE_WINDOW_NOT_MET",
                  "slot_date precedes latest qualifying delivery + notice_days")
    if slot_date < clock_now().date():
        raise_err("ERR_APPOINTMENT_SLOT_PAST",
                  "slot_date is earlier than the current date")
    # Capacity (stage 11): crew bucket strictly below crew_capacity_per_window.
    contractor = db.contractors.get(wo["contractor_id"])
    if contractor is not None:
        bucket = sum(
            1
            for a in db.appointments.values()
            if a["contractor_id"] == contractor["id"]
            and a["status"] in ("BOOKED", "CONFIRMED")
            and a["slot_date"] == slot_date.isoformat()
            and a["window"] == window
        )
        if bucket >= contractor["crew_capacity_per_window"]:
            raise_err("ERR_CREW_WINDOW_FULL",
                      "Contractor crew window is at capacity")
    # Referential (stage 13): assigned contractor must be ACTIVE.
    if contractor is None or contractor["status"] != "ACTIVE":
        raise_err("ERR_CONTRACTOR_NOT_ACTIVE", "Assigned contractor is not ACTIVE")
    # Side effects: supersede existing BOOKED/CONFIRMED, then new appointment.
    for a in db.appointments.values():
        if a["work_order_id"] == wo["id"] and a["status"] in ("BOOKED", "CONFIRMED"):
            a["status"] = "SUPERSEDED"
            touch(a)
    prior_non_superseded = sum(
        1
        for a in db.appointments.values()
        if a["work_order_id"] == wo["id"] and a["status"] != "SUPERSEDED"
    )
    appt = base_resource()
    appt.update({
        "work_order_id": wo["id"],
        "contractor_id": wo["contractor_id"],
        "slot_date": slot_date.isoformat(),
        "window": window,
        "attempt_number": 1 + prior_non_superseded,
        "status": "BOOKED",
    })
    db.appointments[appt["id"]] = appt
    wo["lifecycle_status"] = "SCHEDULED"
    touch(wo)
    return ok_object(ser_appointment(appt), 201)


@bp.get("/api/appointments")
@require_roles(*ALL_ROLES)
def list_appointments():
    filters = {}
    for k in ("work_order_id", "contractor_id", "slot_date", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.appointments.values(), filters, ser_appointment)


@bp.get("/api/appointments/<appointmentId>")
@require_roles(*ALL_ROLES)
def get_appointment(appointmentId):
    return ok_object(ser_appointment(
        get_or_404(db.appointments, appointmentId, "Appointment")))


@bp.post("/api/appointments/<appointmentId>/confirm")
@require_roles("CustomerService")
def confirm_appointment(appointmentId):
    a = get_or_404(db.appointments, appointmentId, "Appointment")
    if a["status"] != "BOOKED":
        raise_err("ERR_INVALID_STATE", "Appointment is not BOOKED")
    a["status"] = "CONFIRMED"
    touch(a)
    return ok_object(ser_appointment(a))


@bp.post("/api/appointments/<appointmentId>/complete")
@require_roles("FieldContractor")
def complete_appointment(appointmentId):
    a = get_or_404(db.appointments, appointmentId, "Appointment")
    check_contractor_ownership(a["contractor_id"])
    if a["status"] not in ("BOOKED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE",
                  "Appointment is not BOOKED or CONFIRMED")
    a["status"] = "COMPLETED"
    touch(a)
    return ok_object(ser_appointment(a))


@bp.post("/api/appointments/<appointmentId>/no-access")
@require_roles("FieldContractor")
def no_access_appointment(appointmentId):
    a = get_or_404(db.appointments, appointmentId, "Appointment")
    check_contractor_ownership(a["contractor_id"])
    if a["status"] not in ("BOOKED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE",
                  "Appointment is not BOOKED or CONFIRMED")
    a["status"] = "NO_ACCESS"
    touch(a)
    wo = get_or_404(db.work_orders, a["work_order_id"], "WorkOrder")
    wo["no_access_strikes"] += 1
    if wo["lifecycle_status"] == "SCHEDULED":
        wo["lifecycle_status"] = "ACCESS_FAILED"
    touch(wo)
    # Escalation boundary: the 3rd strike opens a case (PRD 3.4).
    if wo["no_access_strikes"] >= NO_ACCESS_STRIKE_THRESHOLD:
        open_case = any(
            c["work_order_id"] == wo["id"] and c["status"] == "OPEN"
            for c in db.no_access_cases.values()
        )
        if not open_case:
            case = base_resource()
            case.update({
                "work_order_id": wo["id"],
                "stage": "STAGE_1_DOOR_HANGER",
                "strikes_at_open": wo["no_access_strikes"],
                "status": "OPEN",
                "resolution": None,
            })
            db.no_access_cases[case["id"]] = case
            # Auto-create the stage-one DOOR_HANGER notification.
            n = base_resource()
            n.update({
                "work_order_id": wo["id"],
                "no_access_case_id": case["id"],
                "channel": "DOOR_HANGER",
                "sent_at": clock_now(),
                "delivered_at": None,
                "status": "SENT",
            })
            db.notifications[n["id"]] = n
    return ok_object(ser_appointment(a))


@bp.post("/api/appointments/<appointmentId>/cancel")
@require_roles("Scheduler", "CustomerService")
def cancel_appointment(appointmentId):
    a = get_or_404(db.appointments, appointmentId, "Appointment")
    if a["status"] not in ("BOOKED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE",
                  "Appointment is not BOOKED or CONFIRMED")
    # Customer cancellation: no strike, no work-order cascade (PRD 3.4).
    a["status"] = "CANCELLED_BY_CUSTOMER"
    touch(a)
    return ok_object(ser_appointment(a))
