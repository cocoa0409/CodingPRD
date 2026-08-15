"""SiteShift, DeploymentAssignment, TransportTrip, SeatBooking, PPE endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import db
import services as svc
from errors import (
    ERR_BRIEFING_NOT_CURRENT,
    ERR_DOUBLE_BOOKED_SHIFT,
    ERR_DOUBLE_BOOKED_TRIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OUTSIDE_CHECKIN_WINDOW,
    ERR_PPE_NOT_ISSUED,
    ERR_PPE_STOCK_INSUFFICIENT,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SEAT_CAPACITY_REACHED,
    ERR_SHIFT_CAPACITY_REACHED,
    ERR_SHIFT_WINDOW_PASSED,
    ERR_SITE_WINDOW_MISMATCH,
    ERR_TOO_EARLY_FOR_NO_SHOW,
    ERR_VEHICLE_TURNAROUND_CONFLICT,
    ERR_WAIVER_NOT_SIGNED,
    ERR_WEEKLY_HOUR_CAP,
    raise_error,
)
from middleware import ALL_ROLES, authenticate, authorize
from response import paginate, success_list, success_object
from validation import (
    HAZARD_LEVELS,
    PPE_ITEM_TYPES,
    PPE_OUTCOMES,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)
from validators import (
    check_assignment_safety,
    check_confirm_shift_state,
    check_site_window,
    get_assignment_or_404,
    get_booking_or_404,
    get_ppe_or_404,
    get_shift_or_404,
    get_trip_or_404,
    incident_gate,
    load_fk_string,
    posture_gate,
)

bp = Blueprint("field", __name__)


# --- SiteShift ---------------------------------------------------------------------

@bp.post("/vrc/shifts")
def create_shift():
    authenticate()
    authorize(["LogisticsCoordinator"])
    body = get_body()
    incident_id = load_fk_string(body, "incident_id", db.incidents, "Incident")
    check_unknown_fields(body, {"incident_id", "site_name", "hazard_level", "start_at", "end_at", "capacity"})
    if not isinstance(incident_id, str) or not incident_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: incident_id")
    site_name = req_string(body, "site_name")
    hazard = req_enum(body, "hazard_level", HAZARD_LEVELS)
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    if end_at <= start_at:
        raise_error(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    duration = svc.shift_duration_hours(start_at, end_at)
    if duration < Decimal("0.25"):
        raise_error(ERR_INVALID_REQUEST, "Shift duration must be at least 0.25 hours")
    capacity = req_int(body, "capacity", minimum=1)
    incident_gate(db.incidents[incident_id], "shift creation")
    rec = svc.create_record(db.shifts, {
        "incident_id": incident_id,
        "site_name": site_name,
        "hazard_level": hazard,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "duration_hours": duration,
        "status": "SCHEDULED",
    })
    return success_object(svc.shift_view(rec), 201)


@bp.get("/vrc/shifts/<shiftId>")
def get_shift(shiftId):
    authenticate()
    authorize(ALL_ROLES)
    shift = get_shift_or_404(shiftId)
    return success_object(svc.shift_view(shift))


@bp.post("/vrc/shifts/<shiftId>/open-roster")
def open_roster(shiftId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    shift = get_shift_or_404(shiftId)
    get_body()
    incident = db.incidents[shift["incident_id"]]
    incident_gate(incident, "roster opening")
    if shift["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"Shift must be SCHEDULED to open the roster (current: {shift['status']})")
    if db.now() >= shift["end_at"]:
        raise_error(ERR_SHIFT_WINDOW_PASSED, "The shift window has already passed")
    shift["status"] = "OPEN_FOR_ROSTER"
    svc.touch(shift)
    svc.recompute_posture(incident)
    return success_object(svc.shift_view(shift))


@bp.post("/vrc/shifts/<shiftId>/cancel")
def cancel_shift(shiftId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    shift = get_shift_or_404(shiftId)
    get_body()
    incident = db.incidents[shift["incident_id"]]
    incident_gate(incident, "shift cancellation")
    if shift["status"] not in ("SCHEDULED", "OPEN_FOR_ROSTER", "LOCKED"):
        raise_error(ERR_INVALID_STATE, f"Shift must be SCHEDULED, OPEN_FOR_ROSTER or LOCKED to cancel (current: {shift['status']})")
    svc.shift_cancel_cascade(shift)
    shift["status"] = "CANCELLED"
    svc.touch(shift)
    return success_object(svc.shift_view(shift))


# --- DeploymentAssignment --------------------------------------------------------------

def _check_double_booked_shift(volunteer_id, shift, exclude_assignment_id=None):
    if svc.shift_conflict(volunteer_id, shift, exclude_assignment_id):
        raise_error(ERR_DOUBLE_BOOKED_SHIFT, "Candidate shift overlaps one of the volunteer's committed shifts")


@bp.post("/vrc/assignments")
def create_assignment():
    authenticate()
    authorize(["IntakeCoordinator"])
    body = get_body()
    volunteer_id = load_fk_string(body, "volunteer_id", db.volunteers, "Volunteer")
    request_id = load_fk_string(body, "support_request_id", db.support_requests, "SupportRequest")
    shift_id = load_fk_string(body, "site_shift_id", db.shifts, "SiteShift")
    check_unknown_fields(body, {"volunteer_id", "support_request_id", "site_shift_id"})
    for field, value in (("volunteer_id", volunteer_id), ("support_request_id", request_id), ("site_shift_id", shift_id)):
        if not isinstance(value, str) or not value:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    volunteer = db.volunteers[volunteer_id]
    req = db.support_requests[request_id]
    shift = db.shifts[shift_id]
    incident = db.incidents[req["incident_id"]]
    incident_gate(incident, "assignment creation")
    posture_gate(incident)
    if req["status"] not in ("OPEN", "MATCHING"):
        raise_error(ERR_INVALID_STATE, f"Support request must be OPEN or MATCHING to propose an assignment (current: {req['status']})")
    check_assignment_safety(volunteer, req, shift)
    if shift["incident_id"] != req["incident_id"] or volunteer["incident_id"] != req["incident_id"]:
        raise_error(ERR_SITE_WINDOW_MISMATCH, "Shift and volunteer must belong to the request's incident")
    check_site_window(req, shift)
    _check_double_booked_shift(volunteer["id"], shift)
    rec = svc.create_record(db.assignments, {
        "incident_id": req["incident_id"],
        "volunteer_id": volunteer["id"],
        "support_request_id": req["id"],
        "site_shift_id": shift["id"],
        "status": "PROPOSED",
        "origin": "MANUAL",
        "checked_in_at": None,
        "completed_at": None,
    })
    svc.recompute_request_status(req)  # first proposal nudges OPEN -> MATCHING
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(rec), 201)


@bp.get("/vrc/assignments/<assignmentId>")
def get_assignment(assignmentId):
    authenticate()
    authorize(ALL_ROLES)
    a = get_assignment_or_404(assignmentId)
    return success_object(svc.assignment_view(a))


@bp.get("/vrc/assignments")
def list_assignments():
    authenticate()
    authorize(ALL_ROLES)
    records = list(db.assignments.values())
    for param in ("incident_id", "volunteer_id", "support_request_id", "site_shift_id", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [a for a in records if a[param] == value]
    window, page = paginate(records, request.args)
    return success_list([svc.assignment_view(a) for a in window], page)


def _load_assignment_context(assignmentId, operation, demob_allowed=False):
    a = get_assignment_or_404(assignmentId)
    get_body()
    incident = db.incidents[a["incident_id"]]
    incident_gate(incident, operation, demob_allowed=demob_allowed)
    return a, incident


@bp.post("/vrc/assignments/<assignmentId>/accept")
def accept_assignment(assignmentId):
    authenticate()
    authorize(["Volunteer"])
    a, incident = _load_assignment_context(assignmentId, "assignment acceptance")
    if a["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be PROPOSED to accept (current: {a['status']})")
    if g.user_id != a["volunteer_id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only accept their own assignments")
    a["status"] = "ACCEPTED"
    svc.touch(a)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/decline")
def decline_assignment(assignmentId):
    authenticate()
    authorize(["Volunteer"])
    a, incident = _load_assignment_context(assignmentId, "assignment decline")
    if a["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be PROPOSED to decline (current: {a['status']})")
    if g.user_id != a["volunteer_id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only decline their own assignments")
    a["status"] = "DECLINED"
    svc.touch(a)
    svc.recompute_request_status(db.support_requests[a["support_request_id"]])
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/confirm")
def confirm_assignment(assignmentId):
    authenticate()
    authorize(["IntakeCoordinator"])
    a, incident = _load_assignment_context(assignmentId, "assignment confirmation")
    posture_gate(incident)
    if a["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be ACCEPTED to confirm (current: {a['status']})")
    shift = db.shifts[a["site_shift_id"]]
    req = db.support_requests[a["support_request_id"]]
    volunteer = db.volunteers[a["volunteer_id"]]
    check_confirm_shift_state(shift)
    if svc.rostered_count(shift) >= shift["capacity"]:
        raise_error(ERR_SHIFT_CAPACITY_REACHED, "Shift roster is at capacity")
    check_assignment_safety(volunteer, req, shift)
    _check_double_booked_shift(volunteer["id"], shift, exclude_assignment_id=a["id"])
    projected = svc.committed_hours(volunteer["id"]) + svc.hours2(str(shift["duration_hours"]))
    if projected > svc.COMMITTED_HOUR_CAP:
        raise_error(ERR_WEEKLY_HOUR_CAP, "Confirm would push committed_hours above 40.00")
    a["status"] = "CONFIRMED"
    svc.touch(a)
    svc.touch(volunteer)  # committed_hours debited
    svc.recompute_shift_status(shift)     # rostered_count += 1; LOCKED at capacity
    svc.recompute_request_status(req)     # filled_count += 1; FILLED at headcount
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/cancel")
def cancel_assignment_endpoint(assignmentId):
    authenticate()
    authorize(["IntakeCoordinator", "VRCManager"])
    a, incident = _load_assignment_context(assignmentId, "assignment cancellation")
    if a["status"] not in ("PROPOSED", "ACCEPTED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, f"Assignment must be PROPOSED, ACCEPTED or CONFIRMED to cancel (current: {a['status']})")
    counted = a["status"] == "CONFIRMED"
    a["status"] = "CANCELLED"
    svc.touch(a)
    svc.cancel_assignment(a, counted)
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/check-in")
def check_in_assignment(assignmentId):
    authenticate()
    authorize(["SiteSupervisor"])
    a, incident = _load_assignment_context(assignmentId, "check-in")
    posture_gate(incident)
    if a["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be CONFIRMED to check in (current: {a['status']})")
    shift = db.shifts[a["site_shift_id"]]
    if shift["status"] not in ("OPEN_FOR_ROSTER", "LOCKED"):
        raise_error(ERR_INVALID_STATE, f"Shift must be OPEN_FOR_ROSTER or LOCKED to check in (current: {shift['status']})")
    volunteer = db.volunteers[a["volunteer_id"]]
    if not svc.has_current_briefing(volunteer["id"]):
        raise_error(ERR_BRIEFING_NOT_CURRENT, "Volunteer has no current ACTIVE safety briefing")
    if not svc.has_active_waiver(volunteer["id"]):
        raise_error(ERR_WAIVER_NOT_SIGNED, "Volunteer has no ACTIVE liability waiver")
    if not svc.has_issued_ppe(volunteer["id"]):
        raise_error(ERR_PPE_NOT_ISSUED, "Volunteer has no PPE issuance still ISSUED")
    now = db.now()
    if not (shift["start_at"] - timedelta(minutes=30) <= now <= shift["end_at"]):
        raise_error(ERR_OUTSIDE_CHECKIN_WINDOW, "Now is outside the check-in window [start_at - 30min, end_at]")
    a["status"] = "CHECKED_IN"
    a["checked_in_at"] = now
    svc.touch(a)
    if volunteer["status"] == "READY":
        volunteer["status"] = "DEPLOYED"
        svc.touch(volunteer)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/complete")
def complete_assignment(assignmentId):
    authenticate()
    authorize(["SiteSupervisor"])
    a, incident = _load_assignment_context(assignmentId, "assignment completion")
    if a["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, f"Assignment must be CHECKED_IN to complete (current: {a['status']})")
    a["status"] = "COMPLETED"
    a["completed_at"] = db.now()
    svc.touch(a)
    volunteer = db.volunteers[a["volunteer_id"]]
    svc.touch(volunteer)  # committed_hours released
    svc.maybe_undeploy(volunteer)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/no-show")
def no_show_assignment(assignmentId):
    authenticate()
    authorize(["SiteSupervisor"])
    a, incident = _load_assignment_context(assignmentId, "no-show")
    if a["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be CONFIRMED to record a no-show (current: {a['status']})")
    shift = db.shifts[a["site_shift_id"]]
    if db.now() < shift["end_at"]:
        raise_error(ERR_TOO_EARLY_FOR_NO_SHOW, "A no-show may only be recorded at or after the shift's end_at")
    a["status"] = "NO_SHOW"
    svc.touch(a)
    volunteer = db.volunteers[a["volunteer_id"]]
    svc.touch(volunteer)  # committed_hours released + 10 no-show risk points recorded
    svc.release_assignment_effects(a, True)
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(a))


@bp.post("/vrc/assignments/<assignmentId>/recall")
def recall_assignment(assignmentId):
    authenticate()
    authorize(["RiskOfficer"])
    a, incident = _load_assignment_context(assignmentId, "safety recall")
    if a["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, f"Assignment must be CHECKED_IN to recall (current: {a['status']})")
    a["status"] = "RECALLED"
    svc.touch(a)
    svc.release_assignment_effects(a, True)
    svc.maybe_undeploy(db.volunteers[a["volunteer_id"]])
    svc.recompute_posture(incident)
    return success_object(svc.assignment_view(a))


# --- TransportTrip ------------------------------------------------------------------------

@bp.post("/vrc/trips")
def create_trip():
    authenticate()
    authorize(["LogisticsCoordinator"])
    body = get_body()
    incident_id = load_fk_string(body, "incident_id", db.incidents, "Incident")
    shift_id = load_fk_string(body, "site_shift_id", db.shifts, "SiteShift")
    check_unknown_fields(body, {"incident_id", "site_shift_id", "vehicle_id", "seat_capacity", "depart_at", "arrive_estimate_at"})
    if not isinstance(incident_id, str) or not incident_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: incident_id")
    if not isinstance(shift_id, str) or not shift_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: site_shift_id")
    vehicle_id = req_string(body, "vehicle_id")
    seat_capacity = req_int(body, "seat_capacity", minimum=1)
    depart_at = req_datetime(body, "depart_at")
    arrive_at = req_datetime(body, "arrive_estimate_at")
    if arrive_at <= depart_at:
        raise_error(ERR_INVALID_REQUEST, "arrive_estimate_at must be strictly after depart_at")
    incident_gate(db.incidents[incident_id], "trip creation")
    shift = db.shifts[shift_id]
    if shift["incident_id"] != incident_id:
        raise_error(ERR_RESOURCE_NOT_FOUND, "SiteShift does not belong to the trip's incident")
    if svc.vehicle_turnaround_conflict(incident_id, vehicle_id, depart_at, arrive_at):
        raise_error(ERR_VEHICLE_TURNAROUND_CONFLICT, "Vehicle has a conflicting SCHEDULED or DEPARTED trip within the 45-minute turnaround buffer")
    rec = svc.create_record(db.trips, {
        "incident_id": incident_id,
        "site_shift_id": shift_id,
        "vehicle_id": vehicle_id,
        "seat_capacity": seat_capacity,
        "depart_at": depart_at,
        "arrive_estimate_at": arrive_at,
        "status": "SCHEDULED",
    })
    return success_object(svc.trip_view(rec), 201)


@bp.get("/vrc/trips/<tripId>")
def get_trip(tripId):
    authenticate()
    authorize(ALL_ROLES)
    t = get_trip_or_404(tripId)
    return success_object(svc.trip_view(t))


@bp.get("/vrc/trips")
def list_trips():
    authenticate()
    authorize(ALL_ROLES)
    records = list(db.trips.values())
    for param in ("incident_id", "site_shift_id", "vehicle_id", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [t for t in records if t[param] == value]
    window, page = paginate(records, request.args)
    return success_list([svc.trip_view(t) for t in window], page)


@bp.post("/vrc/trips/<tripId>/depart")
def depart_trip(tripId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    t = get_trip_or_404(tripId)
    get_body()
    incident = db.incidents[t["incident_id"]]
    incident_gate(incident, "trip departure")
    posture_gate(incident)
    if t["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"Trip must be SCHEDULED to depart (current: {t['status']})")
    t["status"] = "DEPARTED"
    svc.touch(t)
    return success_object(svc.trip_view(t))


@bp.post("/vrc/trips/<tripId>/arrive")
def arrive_trip(tripId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    t = get_trip_or_404(tripId)
    get_body()
    incident = db.incidents[t["incident_id"]]
    incident_gate(incident, "trip arrival", demob_allowed=True)
    if t["status"] != "DEPARTED":
        raise_error(ERR_INVALID_STATE, f"Trip must be DEPARTED to arrive (current: {t['status']})")
    t["status"] = "ARRIVED"
    svc.touch(t)
    return success_object(svc.trip_view(t))


@bp.post("/vrc/trips/<tripId>/cancel")
def cancel_trip(tripId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    t = get_trip_or_404(tripId)
    get_body()
    incident = db.incidents[t["incident_id"]]
    incident_gate(incident, "trip cancellation")
    if t["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"Only a SCHEDULED trip can be cancelled (current: {t['status']})")
    t["status"] = "CANCELLED"
    svc.cancel_trip_cascade(t)
    svc.touch(t)
    return success_object(svc.trip_view(t))


# --- SeatBooking ----------------------------------------------------------------------------

@bp.post("/vrc/seat-bookings")
def create_seat_booking():
    authenticate()
    authorize(["LogisticsCoordinator"])
    body = get_body()
    trip_id = load_fk_string(body, "trip_id", db.trips, "TransportTrip")
    assignment_id = load_fk_string(body, "assignment_id", db.assignments, "DeploymentAssignment")
    check_unknown_fields(body, {"trip_id", "assignment_id"})
    if not isinstance(trip_id, str) or not trip_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: trip_id")
    if not isinstance(assignment_id, str) or not assignment_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: assignment_id")
    trip = db.trips[trip_id]
    assignment = db.assignments[assignment_id]
    incident_gate(db.incidents[trip["incident_id"]], "seat booking")
    if trip["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"Trip must be SCHEDULED to book seats (current: {trip['status']})")
    if assignment["status"] not in ("CONFIRMED", "CHECKED_IN"):
        raise_error(ERR_INVALID_STATE, f"Assignment must be CONFIRMED or CHECKED_IN to book a seat (current: {assignment['status']})")
    if svc.trip_overlap_conflict(assignment["volunteer_id"], trip):
        raise_error(ERR_DOUBLE_BOOKED_TRIP, "Volunteer already holds a booking on an overlapping trip")
    if any(b["assignment_id"] == assignment_id and b["trip_id"] == trip_id and b["status"] != "CANCELLED"
           for b in db.seat_bookings.values()):
        raise_error(ERR_INVALID_REQUEST, "A live seat booking already exists for this assignment on this trip")
    if svc.booked_seats(trip) >= trip["seat_capacity"]:
        raise_error(ERR_SEAT_CAPACITY_REACHED, "Trip has no free seats")
    rec = svc.create_record(db.seat_bookings, {
        "trip_id": trip_id,
        "assignment_id": assignment_id,
        "volunteer_id": assignment["volunteer_id"],
        "status": "BOOKED",
    })
    svc.touch(trip)  # booked_seats += 1
    return success_object(svc.seat_booking_view(rec), 201)


@bp.get("/vrc/seat-bookings/<bookingId>")
def get_seat_booking(bookingId):
    authenticate()
    authorize(ALL_ROLES)
    b = get_booking_or_404(bookingId)
    return success_object(svc.seat_booking_view(b))


@bp.get("/vrc/seat-bookings")
def list_seat_bookings():
    authenticate()
    authorize(ALL_ROLES)
    records = list(db.seat_bookings.values())
    for param in ("trip_id", "assignment_id", "volunteer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [b for b in records if b[param] == value]
    window, page = paginate(records, request.args)
    return success_list([svc.seat_booking_view(b) for b in window], page)


@bp.post("/vrc/seat-bookings/<bookingId>/board")
def board_seat(bookingId):
    authenticate()
    authorize(["SiteSupervisor"])
    b = get_booking_or_404(bookingId)
    get_body()
    trip = db.trips[b["trip_id"]]
    incident_gate(db.incidents[trip["incident_id"]], "seat boarding")
    if b["status"] != "BOOKED":
        raise_error(ERR_INVALID_STATE, f"Booking must be BOOKED to board (current: {b['status']})")
    if trip["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"Trip must be SCHEDULED to board (current: {trip['status']})")
    if not svc.has_current_briefing(b["volunteer_id"]):
        raise_error(ERR_BRIEFING_NOT_CURRENT, "Volunteer has no current ACTIVE safety briefing")
    if not svc.has_active_waiver(b["volunteer_id"]):
        raise_error(ERR_WAIVER_NOT_SIGNED, "Volunteer has no ACTIVE liability waiver")
    b["status"] = "BOARDED"
    svc.touch(b)
    return success_object(svc.seat_booking_view(b))


@bp.post("/vrc/seat-bookings/<bookingId>/cancel")
def cancel_seat(bookingId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    b = get_booking_or_404(bookingId)
    get_body()
    trip = db.trips[b["trip_id"]]
    incident_gate(db.incidents[trip["incident_id"]], "seat cancellation")
    if b["status"] != "BOOKED":
        raise_error(ERR_INVALID_STATE, f"Only a BOOKED seat can be cancelled directly (current: {b['status']})")
    b["status"] = "CANCELLED"
    svc.touch(b)
    svc.touch(trip)  # booked_seats -= 1
    return success_object(svc.seat_booking_view(b))


@bp.post("/vrc/seat-bookings/<bookingId>/mark-no-show")
def mark_seat_no_show(bookingId):
    authenticate()
    authorize(["SiteSupervisor"])
    b = get_booking_or_404(bookingId)
    get_body()
    trip = db.trips[b["trip_id"]]
    incident_gate(db.incidents[trip["incident_id"]], "seat no-show")
    if b["status"] != "BOOKED":
        raise_error(ERR_INVALID_STATE, f"Booking must be BOOKED to mark no-show (current: {b['status']})")
    if trip["status"] != "DEPARTED":
        raise_error(ERR_INVALID_STATE, f"Trip must be DEPARTED to mark a seat no-show (current: {trip['status']})")
    b["status"] = "NO_SHOW"
    svc.touch(b)
    svc.touch(trip)  # booked_seats -= 1
    return success_object(svc.seat_booking_view(b))


# --- PPEIssuance --------------------------------------------------------------------------------

@bp.post("/vrc/ppe-issuances")
def create_ppe_issuance():
    authenticate()
    authorize(["LogisticsCoordinator"])
    body = get_body()
    volunteer_id = load_fk_string(body, "volunteer_id", db.volunteers, "Volunteer")
    check_unknown_fields(body, {"volunteer_id", "item_type", "quantity"})
    if not isinstance(volunteer_id, str) or not volunteer_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: volunteer_id")
    item_type = req_enum(body, "item_type", PPE_ITEM_TYPES)
    quantity = req_int(body, "quantity", minimum=1)
    volunteer = db.volunteers[volunteer_id]
    incident = db.incidents[volunteer["incident_id"]]
    incident_gate(incident, "PPE issuance")
    if volunteer["status"] not in ("READY", "DEPLOYED"):
        raise_error(ERR_INVALID_STATE, f"Volunteer must be READY or DEPLOYED for PPE issuance (current: {volunteer['status']})")
    if not svc.has_active_waiver(volunteer_id):
        raise_error(ERR_WAIVER_NOT_SIGNED, "Volunteer has no ACTIVE liability waiver")
    if quantity > incident["ppe_stock"][item_type]:
        raise_error(ERR_PPE_STOCK_INSUFFICIENT, "Requested quantity exceeds remaining stock for the item")
    incident["ppe_stock"][item_type] -= quantity
    svc.touch(incident)
    rec = svc.create_record(db.ppe_issuances, {
        "volunteer_id": volunteer_id,
        "item_type": item_type,
        "quantity": quantity,
        "status": "ISSUED",
        "closed_at": None,
    })
    return success_object(svc.ppe_issuance_view(rec), 201)


@bp.post("/vrc/ppe-issuances/<issuanceId>/close")
def close_ppe_issuance(issuanceId):
    authenticate()
    authorize(["LogisticsCoordinator"])
    ppe = get_ppe_or_404(issuanceId)
    body = get_body()
    check_unknown_fields(body, {"outcome"})
    outcome = req_enum(body, "outcome", PPE_OUTCOMES)
    volunteer = db.volunteers[ppe["volunteer_id"]]
    incident = db.incidents[volunteer["incident_id"]]
    incident_gate(incident, "PPE close-out", demob_allowed=True)
    if ppe["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE, f"PPE issuance must be ISSUED to close (current: {ppe['status']})")
    ppe["status"] = outcome
    ppe["closed_at"] = db.now()
    svc.touch(ppe)
    if outcome == "RETURNED":
        incident["ppe_stock"][ppe["item_type"]] += ppe["quantity"]
        svc.touch(incident)
    return success_object(svc.ppe_issuance_view(ppe))
