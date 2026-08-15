"""Student endpoints."""
from flask import Blueprint, request
from datetime import datetime, timezone
from db import store, new_id, now, now_iso
from errors import (
    raise_err, ERR_STUDENT_NOT_FOUND, ERR_PROGRAM_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STUDENT_DELINQUENT_FEES, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import student_out, payment_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from services.ledger import recompute_student, post_ledger
from routes.programs import _get_program_or_404, _program_posture_open

bp = Blueprint("students", __name__)


def _get_student_or_404(sid):
    s = store.students.get(sid)
    if s is None:
        raise_err(ERR_STUDENT_NOT_FOUND, f"student {sid} not found")
    return s


def _refund_tier_pct(departure_at, now_dt):
    """Refund percent per tier: >=14 days 1.00; 7-13 days 0.50; <7 days 0.00."""
    delta_sec = (departure_at - now_dt).total_seconds()
    days = int(delta_sec // 86400)
    if days >= 14:
        return 1.0
    if days >= 7:
        return 0.5
    return 0.0


def _waitlist_promotion(trip):
    """Promote earliest-created WAITLISTED enrollment if roster has space."""
    from services.ledger import round_half_up_cents
    registered = [e for e in store.trip_enrollments.values()
                  if e["trip_id"] == trip["id"] and e["attendance_status"] in ("REGISTERED", "CONFIRMED")]
    if len(registered) >= trip["capacity"]:
        return
    candidates = [e for e in store.trip_enrollments.values()
                  if e["trip_id"] == trip["id"] and e["attendance_status"] == "WAITLISTED"]
    if not candidates:
        return
    candidates.sort(key=lambda e: e["created_at"])
    promoted = candidates[0]
    new_count = len(registered) + 1
    promoted["attendance_status"] = "REGISTERED"
    prov = round_half_up_cents(trip["estimated_cost_cents"] / new_count) if new_count > 0 else 0
    promoted["provisional_share_cents"] = prov
    promoted["amount_due_cents"] = prov
    promoted["version"] += 1
    promoted["updated_at"] = now_iso()
    from services.ledger import recompute_enrollment
    recompute_enrollment(promoted)


def _recompute_trip_counts(trip):
    reg = sum(1 for e in store.trip_enrollments.values()
              if e["trip_id"] == trip["id"] and e["attendance_status"] in ("REGISTERED", "CONFIRMED"))
    conf = sum(1 for e in store.trip_enrollments.values()
               if e["trip_id"] == trip["id"] and e["attendance_status"] == "CONFIRMED")
    trip["registered_count"] = reg
    trip["confirmed_count"] = conf


@bp.route("/band/students", methods=["POST"])
def create_student():
    uid, role = require_roles(["BandDirector", "AssistantDirector"])
    data = body()
    check_unknown(data, {"program_id", "full_name", "grade", "section"})
    require(data, "program_id", "full_name", "grade", "section")
    pid = to_str(data["program_id"], "program_id")
    full_name = to_str(data["full_name"], "full_name")
    grade = to_int(data["grade"], "grade")
    section = to_enum(data["section"], "section", {"WOODWIND", "BRASS", "PERCUSSION", "GUARD"})

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    sid = new_id()
    now_s = now_iso()
    s = {
        "id": sid,
        "program_id": pid,
        "full_name": full_name,
        "grade": grade,
        "section": section,
        "is_section_leader": False,
        "enrollment_status": "APPLIED",
        "account_balance_cents": 0,
        "is_delinquent": False,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.students[sid] = s
    return success(student_out(s), status=201)


@bp.route("/band/students", methods=["GET"])
def list_students():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.students.values())
    pid = request.args.get("program_id")
    if pid:
        items = [s for s in items if s["program_id"] == pid]
    sect = request.args.get("section")
    if sect:
        items = [s for s in items if s["section"] == sect]
    es = request.args.get("enrollment_status")
    if es:
        items = [s for s in items if s["enrollment_status"] == es]
    items.sort(key=lambda s: s["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([student_out(s) for s in page], is_list=True, pagination=pag)


@bp.route("/band/students/<sid>", methods=["GET"])
def get_student(sid):
    require_roles(["Any"])
    apply_time_transitions()
    s = _get_student_or_404(sid)
    return success(student_out(s))


@bp.route("/band/students/<sid>/enroll", methods=["POST"])
def enroll_student(sid):
    require_roles(["BandDirector", "AssistantDirector"])
    s = _get_student_or_404(sid)
    if s["enrollment_status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "student is not APPLIED")
    s["enrollment_status"] = "ENROLLED"
    s["version"] += 1
    s["updated_at"] = now_iso()
    return success(student_out(s))


@bp.route("/band/students/<sid>/suspend", methods=["POST"])
def suspend_student(sid):
    require_roles(["BandDirector"])
    s = _get_student_or_404(sid)
    if s["enrollment_status"] != "ENROLLED":
        raise_err(ERR_INVALID_STATE, "student is not ENROLLED")
    s["enrollment_status"] = "SUSPENDED"
    s["version"] += 1
    s["updated_at"] = now_iso()
    return success(student_out(s))


@bp.route("/band/students/<sid>/reinstate", methods=["POST"])
def reinstate_student(sid):
    require_roles(["BandDirector"])
    s = _get_student_or_404(sid)
    if s["enrollment_status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "student is not SUSPENDED")
    program = _get_program_or_404(s["program_id"])
    if s["account_balance_cents"] > program["delinquency_grace_cents"]:
        raise_err(ERR_STUDENT_DELINQUENT_FEES, "student balance exceeds delinquency grace")
    s["enrollment_status"] = "ENROLLED"
    s["version"] += 1
    s["updated_at"] = now_iso()
    return success(student_out(s))


@bp.route("/band/students/<sid>/withdraw", methods=["POST"])
def withdraw_student(sid):
    require_roles(["BandDirector"])
    apply_time_transitions()
    s = _get_student_or_404(sid)
    if s["enrollment_status"] not in ("ENROLLED", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "student is not ENROLLED or SUSPENDED")
    n = now()

    # 1. Force-return instrument assignments
    for a in list(store.instrument_assignments.values()):
        if a["student_id"] != sid:
            continue
        if a["status"] not in ("ACTIVE", "OVERDUE"):
            continue
        # late fee if past due
        if n > a["due_date"]:
            from db import days_ceil
            days = days_ceil(n, a["due_date"])
            weeks = max(1, (days + 6) // 7)
            late_fee = weeks * 500
            a["late_fee_cents"] = late_fee
            if late_fee > 0:
                post_ledger(sid, "LATE_FEE_DEBIT", late_fee, note=None)
        a["status"] = "RETURNED"
        a["returned_at"] = now_iso()
        a["version"] += 1
        a["updated_at"] = now_iso()
        instr = store.instruments.get(a["instrument_id"])
        if instr:
            instr["status"] = "RETURN_PENDING_INSPECTION"
            instr["version"] += 1
            instr["updated_at"] = now_iso()

    # 2. Force-return uniform assignments
    for ua in list(store.uniform_assignments.values()):
        if ua["student_id"] != sid:
            continue
        if ua["status"] != "ISSUED":
            continue
        ua["status"] = "RETURNED"
        ua["returned_at"] = now_iso()
        ua["soiling_level"] = "NORMAL"
        ua["version"] += 1
        ua["updated_at"] = now_iso()
        u = store.uniforms.get(ua["uniform_id"])
        if u:
            u["status"] = "RETURNED_DIRTY"
            u["version"] += 1
            u["updated_at"] = now_iso()

    # 3. Excuse trip enrollments with refunds
    from decimal import Decimal, ROUND_HALF_UP
    for te in list(store.trip_enrollments.values()):
        if te["student_id"] != sid:
            continue
        if te["attendance_status"] not in ("REGISTERED", "CONFIRMED"):
            continue
        trip = store.trips.get(te["trip_id"])
        if not trip:
            continue
        # Compute refund per tier. Capture net paid BEFORE posting the refund:
        # post_ledger recomputes the enrollment's derived fields, zeroing
        # net_paid_cents for a full refund.
        pct = _refund_tier_pct(trip["departure_at"], n)
        net_paid_before = te["net_paid_cents"]
        refund_cents = int(Decimal(str(net_paid_before * pct)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        te["attendance_status"] = "EXCUSED"
        if refund_cents > 0:
            post_ledger(sid, "REFUND", refund_cents, trip_enrollment_id=te["id"])
            # PRD §3.6: full refund of a positive net paid -> REFUNDED.
            if refund_cents == net_paid_before and net_paid_before > 0:
                te["payment_status"] = "REFUNDED"
        te["version"] += 1
        te["updated_at"] = now_iso()
        # recompute payment_status post-refund (unless already REFUNDED)
        from services.ledger import recompute_enrollment
        if te["payment_status"] != "REFUNDED":
            recompute_enrollment(te)
        # update trip counts
        _recompute_trip_counts(trip)
        trip["version"] += 1
        trip["updated_at"] = now_iso()
        # waitlist promotion
        _waitlist_promotion(trip)
        _recompute_trip_counts(trip)

    s["enrollment_status"] = "WITHDRAWN"
    s["version"] += 1
    s["updated_at"] = now_iso()
    recompute_student(s)
    return success(student_out(s))


@bp.route("/band/students/<sid>/designate-leader", methods=["POST"])
def designate_leader(sid):
    require_roles(["BandDirector"])
    s = _get_student_or_404(sid)
    s["is_section_leader"] = True
    s["version"] += 1
    s["updated_at"] = now_iso()
    return success(student_out(s))


@bp.route("/band/students/<sid>/ledger", methods=["GET"])
def student_ledger(sid):
    require_roles(["Any"])
    apply_time_transitions()
    s = _get_student_or_404(sid)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.payments.values() if p["student_id"] == sid]
    items.sort(key=lambda p: p["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([payment_out(p) for p in page], is_list=True, pagination=pag)
