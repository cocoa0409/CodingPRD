"""Trip + TripEnrollment endpoints."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt
from errors import (
    raise_err, ERR_TRIP_NOT_FOUND, ERR_TRIP_ENROLLMENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND, ERR_STUDENT_NOT_FOUND, ERR_PROGRAM_NOT_FOUND,
    ERR_TRIP_ROSTER_NOT_OPEN, ERR_TRIP_NOT_LOCKED, ERR_ENROLLMENT_NOT_CONFIRMABLE,
    ERR_ENROLLMENT_NOT_PAID, ERR_ENROLLMENT_TERMINAL, ERR_UNRESOLVED_ENROLLMENTS_EXIST,
    ERR_EVENT_HAS_ACTIVE_TRIP, ERR_ENROLLMENT_DUPLICATE, ERR_STUDENT_NOT_ENROLLED,
    ERR_STUDENT_DELINQUENT_FEES, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
    ERR_CHARTER_REQUIRED, ERR_FORBIDDEN_OWNERSHIP, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import trip_out, trip_enrollment_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from services.ledger import post_ledger, recompute_enrollment, recompute_student, round_half_up_cents
from routes.programs import _get_program_or_404
from routes.events import _get_event_or_404, _cancel_event_cascade
from routes.students import _get_student_or_404, _waitlist_promotion, _recompute_trip_counts, _refund_tier_pct

bp = Blueprint("trips", __name__)


def _get_trip_or_404(tid):
    t = store.trips.get(tid)
    if t is None:
        raise_err(ERR_TRIP_NOT_FOUND, f"trip {tid} not found")
    return t


def _get_enrollment_or_404(eid):
    e = store.trip_enrollments.get(eid)
    if e is None:
        raise_err(ERR_TRIP_ENROLLMENT_NOT_FOUND, f"trip enrollment {eid} not found")
    return e


@bp.route("/band/trips", methods=["POST"])
def create_trip():
    require_roles(["BandDirector", "AssistantDirector"])
    data = body()
    check_unknown(data, {"event_id", "expected_event_version", "capacity",
                         "estimated_cost_cents", "departure_at"})
    require(data, "event_id", "expected_event_version", "capacity",
            "estimated_cost_cents", "departure_at")
    event_id = to_str(data["event_id"], "event_id")
    expected_event_version = to_int(data["expected_event_version"], "expected_event_version")
    capacity = to_int(data["capacity"], "capacity")
    estimated_cost_cents = to_int(data["estimated_cost_cents"], "estimated_cost_cents")
    try:
        departure_at = parse_dt(data["departure_at"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "departure_at must be ISO8601")

    event = _get_event_or_404(event_id)
    if event["version"] != expected_event_version:
        raise_err(ERR_STALE_VERSION, "expected_event_version does not match current version")
    program = _get_program_or_404(event["program_id"])

    # Check existing trips for this event
    for t in store.trips.values():
        if t["event_id"] == event_id and t["status"] != "SUPERSEDED":
            if t["status"] == "PLANNING":
                # supersede
                t["status"] = "SUPERSEDED"
                t["version"] += 1
                t["updated_at"] = now_iso()
            else:
                raise_err(ERR_EVENT_HAS_ACTIVE_TRIP, "event already has a trip beyond PLANNING")

    tid = new_id()
    now_s = now_iso()
    t = {
        "id": tid,
        "event_id": event_id,
        "program_id": event["program_id"],
        "status": "PLANNING",
        "capacity": capacity,
        "estimated_cost_cents": estimated_cost_cents,
        "actual_cost_cents": None,
        "subsidy_applied_cents": 0,
        "departure_at": departure_at,
        "registered_count": 0,
        "confirmed_count": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.trips[tid] = t
    # increment event version
    event["version"] += 1
    event["updated_at"] = now_s
    return success(trip_out(t), status=201)


@bp.route("/band/trips", methods=["GET"])
def list_trips():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.trips.values())
    eid = request.args.get("event_id")
    if eid:
        items = [t for t in items if t["event_id"] == eid]
    pid = request.args.get("program_id")
    if pid:
        items = [t for t in items if t["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [t for t in items if t["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([trip_out(t) for t in page], is_list=True, pagination=pag)


@bp.route("/band/trips/<tid>", methods=["GET"])
def get_trip(tid):
    require_roles(["Any"])
    apply_time_transitions()
    t = _get_trip_or_404(tid)
    return success(trip_out(t))


@bp.route("/band/trips/<tid>/open-roster", methods=["POST"])
def open_roster(tid):
    require_roles(["BandDirector", "AssistantDirector"])
    t = _get_trip_or_404(tid)
    if t["status"] != "PLANNING":
        raise_err(ERR_TRIP_ROSTER_NOT_OPEN, "trip is not PLANNING")
    t["status"] = "ROSTER_OPEN"
    t["version"] += 1
    t["updated_at"] = now_iso()
    return success(trip_out(t))


@bp.route("/band/trips/<tid>/lock-roster", methods=["POST"])
def lock_roster(tid):
    require_roles(["BandDirector", "AssistantDirector"])
    t = _get_trip_or_404(tid)
    if t["status"] != "ROSTER_OPEN":
        raise_err(ERR_TRIP_ROSTER_NOT_OPEN, "trip is not ROSTER_OPEN")
    # Require a TruckCharter for the event
    has_charter = False
    for tc in store.truck_charters.values():
        if tc.get("event_id") == t["event_id"] and tc["status"] in ("RESERVED", "LOADED", "DEPARTED", "RETURNED"):
            has_charter = True
            break
    if not has_charter:
        raise_err(ERR_CHARTER_REQUIRED, "no active charter for the trip's event")
    t["status"] = "ROSTER_LOCKED"
    t["version"] += 1
    t["updated_at"] = now_iso()
    return success(trip_out(t))


@bp.route("/band/trips/<tid>/finalize", methods=["POST"])
def finalize_trip(tid):
    require_roles(["BoosterTreasurer"])
    t = _get_trip_or_404(tid)
    data = body()
    check_unknown(data, {"actual_cost_cents"})
    require(data, "actual_cost_cents")
    actual_cost_cents = to_int(data["actual_cost_cents"], "actual_cost_cents")
    if actual_cost_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "actual_cost_cents must be non-negative")
    if t["status"] != "ROSTER_LOCKED":
        raise_err(ERR_TRIP_NOT_LOCKED, "trip is not ROSTER_LOCKED")
    # PINNED ORDER
    confirmed = [e for e in store.trip_enrollments.values()
                 if e["trip_id"] == tid and e["attendance_status"] == "CONFIRMED"]
    if not confirmed:
        raise_err(ERR_INVALID_STATE, "no confirmed enrollments")
    confirmed_count = len(confirmed)
    gross = actual_cost_cents
    program = _get_program_or_404(t["program_id"])
    subsidy_cap = round_half_up_cents(Decimal("0.25") * Decimal(gross))
    subsidy_applied = min(program["subsidy_pool_cents"], subsidy_cap)
    net = gross - subsidy_applied
    final_share = round_half_up_cents(Decimal(net) / Decimal(confirmed_count))

    t["actual_cost_cents"] = actual_cost_cents
    t["subsidy_applied_cents"] = subsidy_applied
    t["status"] = "FINALIZED"
    t["version"] += 1
    t["updated_at"] = now_iso()

    for e in confirmed:
        e["final_share_cents"] = final_share
        e["amount_due_cents"] = final_share
        e["version"] += 1
        e["updated_at"] = now_iso()
        post_ledger(e["student_id"], "TRIP_SHARE_DEBIT", final_share, trip_enrollment_id=e["id"])
        recompute_enrollment(e)
        student = store.students.get(e["student_id"])
        if student:
            recompute_student(student)

    _recompute_trip_counts(t)
    return success(trip_out(t))


@bp.route("/band/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    require_roles(["BandDirector"])
    t = _get_trip_or_404(tid)
    if t["status"] not in ("PLANNING", "ROSTER_OPEN", "ROSTER_LOCKED", "FINALIZED"):
        raise_err(ERR_INVALID_STATE, "trip is in terminal state")
    t["status"] = "CANCELLED"
    t["version"] += 1
    t["updated_at"] = now_iso()
    # cascade enrollments
    for te in list(store.trip_enrollments.values()):
        if te["trip_id"] != tid:
            continue
        if te["attendance_status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
            te["attendance_status"] = "EXCUSED"
            if te["net_paid_cents"] > 0:
                refund = te["net_paid_cents"]
                post_ledger(te["student_id"], "REFUND", refund, trip_enrollment_id=te["id"])
                te["payment_status"] = "REFUNDED"
            te["version"] += 1
            te["updated_at"] = now_iso()
            student = store.students.get(te["student_id"])
            if student:
                recompute_student(student)
    return success(trip_out(t))


@bp.route("/band/trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    require_roles(["BandDirector", "AssistantDirector"])
    t = _get_trip_or_404(tid)
    if t["status"] != "FINALIZED":
        raise_err(ERR_TRIP_NOT_LOCKED, "trip is not FINALIZED")
    for te in store.trip_enrollments.values():
        if te["trip_id"] == tid and te["attendance_status"] not in ("ATTENDED", "NO_SHOW", "EXCUSED"):
            raise_err(ERR_UNRESOLVED_ENROLLMENTS_EXIST, "unresolved attendance remains")
    t["status"] = "COMPLETED"
    t["version"] += 1
    t["updated_at"] = now_iso()
    return success(trip_out(t))


# -------- TripEnrollment --------

@bp.route("/band/trip-enrollments", methods=["POST"])
def create_enrollment():
    uid, role = require_roles(["BandDirector", "AssistantDirector", "Student"])
    data = body()
    check_unknown(data, {"trip_id", "student_id"})
    require(data, "trip_id", "student_id")
    trip_id = to_str(data["trip_id"], "trip_id")
    student_id = to_str(data["student_id"], "student_id")

    # Ownership for Student role
    if role == "Student" and student_id != uid:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Student may only enroll self")

    trip = _get_trip_or_404(trip_id)
    student = _get_student_or_404(student_id)

    if student["enrollment_status"] != "ENROLLED":
        raise_err(ERR_STUDENT_NOT_ENROLLED, "student must be ENROLLED")

    # Duplicate check
    for e in store.trip_enrollments.values():
        if e["trip_id"] == trip_id and e["student_id"] == student_id and \
           e["attendance_status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
            raise_err(ERR_ENROLLMENT_DUPLICATE, "student already has a non-terminal enrollment for this trip")

    # Fiscal: delinquency
    program = _get_program_or_404(trip["program_id"])
    if student["account_balance_cents"] > program["delinquency_grace_cents"]:
        raise_err(ERR_STUDENT_DELINQUENT_FEES, "student is delinquent")

    # Capacity check
    registered_count = sum(1 for e in store.trip_enrollments.values()
                           if e["trip_id"] == trip_id and e["attendance_status"] in ("REGISTERED", "CONFIRMED"))
    will_be_waitlisted = registered_count >= trip["capacity"]

    eid = new_id()
    now_s = now_iso()
    if will_be_waitlisted:
        attendance_status = "WAITLISTED"
        provisional = 0
        amount_due = 0
    else:
        attendance_status = "REGISTERED"
        new_count = registered_count + 1
        provisional = round_half_up_cents(Decimal(trip["estimated_cost_cents"]) / Decimal(new_count))
        amount_due = provisional

    e = {
        "id": eid,
        "trip_id": trip_id,
        "student_id": student_id,
        "attendance_status": attendance_status,
        "payment_status": "UNPAID",
        "provisional_share_cents": provisional,
        "amount_due_cents": amount_due,
        "final_share_cents": None,
        "net_paid_cents": 0,
        "refunded_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.trip_enrollments[eid] = e
    _recompute_trip_counts(trip)
    trip["version"] += 1
    trip["updated_at"] = now_s
    return success(trip_enrollment_out(e), status=201)


@bp.route("/band/trip-enrollments", methods=["GET"])
def list_enrollments():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.trip_enrollments.values())
    tid = request.args.get("trip_id")
    if tid:
        items = [e for e in items if e["trip_id"] == tid]
    sid = request.args.get("student_id")
    if sid:
        items = [e for e in items if e["student_id"] == sid]
    ps = request.args.get("payment_status")
    if ps:
        items = [e for e in items if e["payment_status"] == ps]
    ats = request.args.get("attendance_status")
    if ats:
        items = [e for e in items if e["attendance_status"] == ats]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([trip_enrollment_out(e) for e in page], is_list=True, pagination=pag)


@bp.route("/band/trip-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    require_roles(["Any"])
    apply_time_transitions()
    e = _get_enrollment_or_404(eid)
    return success(trip_enrollment_out(e))


@bp.route("/band/trip-enrollments/<eid>/confirm", methods=["POST"])
def confirm_enrollment(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_enrollment_or_404(eid)
    if e["attendance_status"] != "REGISTERED":
        raise_err(ERR_ENROLLMENT_NOT_CONFIRMABLE, "enrollment is not REGISTERED")
    trip = _get_trip_or_404(e["trip_id"])
    if trip["status"] not in ("ROSTER_OPEN", "ROSTER_LOCKED"):
        raise_err(ERR_TRIP_ROSTER_NOT_OPEN, "trip roster is not open")
    if e["payment_status"] != "PAID":
        raise_err(ERR_ENROLLMENT_NOT_PAID, "enrollment is not PAID")
    e["attendance_status"] = "CONFIRMED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    _recompute_trip_counts(trip)
    trip["version"] += 1
    trip["updated_at"] = now_iso()
    return success(trip_enrollment_out(e))


@bp.route("/band/trip-enrollments/<eid>/excuse", methods=["POST"])
def excuse_enrollment(eid):
    uid, role = require_roles(["BandDirector", "AssistantDirector", "Student"])
    e = _get_enrollment_or_404(eid)
    if role == "Student" and e["student_id"] != uid:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Student may only excuse self")
    if e["attendance_status"] not in ("REGISTERED", "CONFIRMED"):
        raise_err(ERR_ENROLLMENT_TERMINAL, "enrollment is in terminal state")
    trip = _get_trip_or_404(e["trip_id"])
    n = now()
    pct = _refund_tier_pct(trip["departure_at"], n)
    # Capture net paid BEFORE posting the refund: post_ledger recomputes the
    # enrollment's derived fields, zeroing net_paid_cents for a full refund.
    net_paid_before = e["net_paid_cents"]
    refund_cents = int(Decimal(str(net_paid_before * pct)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    e["attendance_status"] = "EXCUSED"
    if refund_cents > 0:
        post_ledger(e["student_id"], "REFUND", refund_cents, trip_enrollment_id=e["id"])
        # PRD §3.6: when the refund equals the full net paid and the net paid
        # is positive, payment_status moves to REFUNDED.
        if refund_cents == net_paid_before and net_paid_before > 0:
            e["payment_status"] = "REFUNDED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    if e["payment_status"] != "REFUNDED":
        recompute_enrollment(e)
    student = store.students.get(e["student_id"])
    if student:
        recompute_student(student)

    _recompute_trip_counts(trip)
    trip["version"] += 1
    trip["updated_at"] = now_iso()
    _waitlist_promotion(trip)
    _recompute_trip_counts(trip)
    return success(trip_enrollment_out(e))


@bp.route("/band/trip-enrollments/<eid>/mark-attendance", methods=["POST"])
def mark_attendance(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_enrollment_or_404(eid)
    data = body()
    check_unknown(data, {"outcome"})
    require(data, "outcome")
    outcome = to_enum(data["outcome"], "outcome", {"ATTENDED", "NO_SHOW"})
    if e["attendance_status"] != "CONFIRMED":
        raise_err(ERR_ENROLLMENT_NOT_CONFIRMABLE, "enrollment is not CONFIRMED")
    trip = _get_trip_or_404(e["trip_id"])
    if trip["status"] != "FINALIZED":
        raise_err(ERR_TRIP_NOT_LOCKED, "trip is not FINALIZED")
    e["attendance_status"] = outcome
    e["version"] += 1
    e["updated_at"] = now_iso()
    _recompute_trip_counts(trip)
    trip["version"] += 1
    trip["updated_at"] = now_iso()
    return success(trip_enrollment_out(e))
