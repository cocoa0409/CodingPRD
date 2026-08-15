"""Payment + Fundraiser endpoints."""
from decimal import Decimal, ROUND_FLOOR
from flask import Blueprint, request
from db import store, new_id, now, now_iso
from errors import (
    raise_err, ERR_PAYMENT_NOT_FOUND, ERR_FUNDRAISER_NOT_FOUND,
    ERR_STUDENT_NOT_FOUND, ERR_TRIP_ENROLLMENT_NOT_FOUND,
    ERR_FUNDRAISER_NOT_OPEN, ERR_STUDENT_NOT_ENROLLED,
    ERR_INVALID_REQUEST, ERR_REFUND_EXCEEDS_PAID,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import payment_out, fundraiser_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from services.ledger import (
    post_ledger, recompute_enrollment, recompute_student,
    run_waterfall, net_cash_paid, CLIENT_POSTABLE_KINDS, SYSTEM_ONLY_KINDS,
)
from routes.programs import _get_program_or_404, _program_posture_open
from routes.students import _get_student_or_404

bp = Blueprint("payments", __name__)


def _get_payment_or_404(pid):
    p = store.payments.get(pid)
    if p is None:
        raise_err(ERR_PAYMENT_NOT_FOUND, f"payment {pid} not found")
    return p


def _get_fundraiser_or_404(fid):
    f = store.fundraisers.get(fid)
    if f is None:
        raise_err(ERR_FUNDRAISER_NOT_FOUND, f"fundraiser {fid} not found")
    return f


@bp.route("/band/payments", methods=["POST"])
def create_payment():
    require_roles(["BoosterTreasurer"])
    data = body()
    check_unknown(data, {"student_id", "kind", "amount_cents", "trip_enrollment_id",
                         "reference_payment_id", "note"})
    require(data, "student_id", "kind", "amount_cents")
    student_id = to_str(data["student_id"], "student_id")
    kind = to_enum(data["kind"], "kind",
                   {"PAYMENT", "REFUND", "WAIVER", "MANUAL_DEBIT",
                    "RENTAL_FEE_DEBIT", "LATE_FEE_DEBIT", "CLEANING_FEE_DEBIT",
                    "TRIP_SHARE_DEBIT", "FUNDRAISING_CREDIT"})
    amount_cents = to_int(data["amount_cents"], "amount_cents")
    trip_enrollment_id = data.get("trip_enrollment_id")
    reference_payment_id = data.get("reference_payment_id")
    note = data.get("note")
    if note is not None:
        note = to_str(note, "note")

    # System-only kinds rejected
    if kind in SYSTEM_ONLY_KINDS:
        raise_err(ERR_INVALID_REQUEST, f"kind {kind} is system-only")
    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be positive")

    student = _get_student_or_404(student_id)

    # Existence of trip_enrollment_id / reference_payment_id
    if trip_enrollment_id is not None:
        trip_enrollment_id = to_str(trip_enrollment_id, "trip_enrollment_id")
        if trip_enrollment_id not in store.trip_enrollments:
            raise_err(ERR_TRIP_ENROLLMENT_NOT_FOUND, f"trip enrollment {trip_enrollment_id} not found")
    if kind in ("REFUND", "WAIVER"):
        if reference_payment_id is None:
            raise_err(ERR_INVALID_REQUEST, "reference_payment_id is required for REFUND/WAIVER")
        reference_payment_id = to_str(reference_payment_id, "reference_payment_id")
        if reference_payment_id not in store.payments:
            raise_err(ERR_PAYMENT_NOT_FOUND, f"payment {reference_payment_id} not found")
    elif reference_payment_id is not None:
        reference_payment_id = to_str(reference_payment_id, "reference_payment_id")
        if reference_payment_id not in store.payments:
            raise_err(ERR_PAYMENT_NOT_FOUND, f"payment {reference_payment_id} not found")

    # REFUND: must not exceed net cash paid
    if kind == "REFUND":
        if amount_cents > net_cash_paid(student_id):
            raise_err(ERR_REFUND_EXCEEDS_PAID, "refund exceeds net cash paid")
        # NO_SHOW negative-space rule: no REFUND may be posted against a NO_SHOW enrollment
        if trip_enrollment_id is not None:
            te = store.trip_enrollments.get(trip_enrollment_id)
            if te and te["attendance_status"] == "NO_SHOW":
                raise_err(ERR_INVALID_REQUEST,
                          "REFUND may not be posted against a NO_SHOW enrollment")

    allocations = []
    if kind == "PAYMENT":
        allocations = run_waterfall(student, amount_cents)

    row = post_ledger(student_id, kind, amount_cents,
                      trip_enrollment_id=trip_enrollment_id,
                      reference_payment_id=reference_payment_id,
                      note=note, allocations=allocations)
    return success(payment_out(row), status=201)


@bp.route("/band/payments", methods=["GET"])
def list_payments():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.payments.values())
    sid = request.args.get("student_id")
    if sid:
        items = [p for p in items if p["student_id"] == sid]
    teid = request.args.get("trip_enrollment_id")
    if teid:
        items = [p for p in items if p.get("trip_enrollment_id") == teid]
    fid = request.args.get("fundraiser_id")
    if fid:
        items = [p for p in items if p.get("fundraiser_id") == fid]
    kd = request.args.get("kind")
    if kd:
        items = [p for p in items if p["kind"] == kd]
    rid = request.args.get("reference_payment_id")
    if rid:
        items = [p for p in items if p.get("reference_payment_id") == rid]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([payment_out(p) for p in page], is_list=True, pagination=pag)


@bp.route("/band/payments/<pid>", methods=["GET"])
def get_payment(pid):
    require_roles(["Any"])
    apply_time_transitions()
    p = _get_payment_or_404(pid)
    return success(payment_out(p))


# -------- Fundraiser --------

@bp.route("/band/fundraisers", methods=["POST"])
def create_fundraiser():
    require_roles(["BoosterTreasurer"])
    data = body()
    check_unknown(data, {"program_id", "name", "goal_cents"})
    require(data, "program_id", "name", "goal_cents")
    pid = to_str(data["program_id"], "program_id")
    name = to_str(data["name"], "name")
    goal_cents = to_int(data["goal_cents"], "goal_cents")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    fid = new_id()
    now_s = now_iso()
    f = {
        "id": fid,
        "program_id": pid,
        "name": name,
        "goal_cents": goal_cents,
        "status": "OPEN",
        "raised_cents": None,
        "allocated_credit_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.fundraisers[fid] = f
    return success(fundraiser_out(f), status=201)


@bp.route("/band/fundraisers", methods=["GET"])
def list_fundraisers():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.fundraisers.values())
    pid = request.args.get("program_id")
    if pid:
        items = [f for f in items if f["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [f for f in items if f["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([fundraiser_out(f) for f in page], is_list=True, pagination=pag)


@bp.route("/band/fundraisers/<fid>", methods=["GET"])
def get_fundraiser(fid):
    require_roles(["Any"])
    apply_time_transitions()
    f = _get_fundraiser_or_404(fid)
    return success(fundraiser_out(f))


@bp.route("/band/fundraisers/<fid>/close", methods=["POST"])
def close_fundraiser(fid):
    require_roles(["BoosterTreasurer"])
    f = _get_fundraiser_or_404(fid)
    data = body()
    check_unknown(data, {"raised_cents", "participant_hours"})
    require(data, "raised_cents", "participant_hours")
    raised_cents = to_int(data["raised_cents"], "raised_cents")
    if raised_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "raised_cents must be non-negative")
    ph = data["participant_hours"]
    # participant_hours supplies each participating student's hours (PRD §3.7);
    # accept either a {student_id: hours} object or a list of
    # {"student_id": ..., "hours": ...} entries.
    ph_items = []
    if isinstance(ph, dict):
        ph_items = list(ph.items())
    elif isinstance(ph, list):
        for entry in ph:
            if not isinstance(entry, dict) or "student_id" not in entry or "hours" not in entry:
                raise_err(ERR_INVALID_REQUEST,
                          "participant_hours entries must carry student_id and hours")
            ph_items.append((entry["student_id"], entry["hours"]))
    if not ph_items:
        raise_err(ERR_INVALID_REQUEST, "participant_hours must be non-empty")

    if f["status"] != "OPEN":
        raise_err(ERR_FUNDRAISER_NOT_OPEN, "fundraiser is not OPEN")

    # Validate participants
    participants = []
    for sid, hours in ph_items:
        student = store.students.get(sid)
        if student is None:
            raise_err(ERR_STUDENT_NOT_FOUND, f"student {sid} not found")
        if student["enrollment_status"] != "ENROLLED":
            raise_err(ERR_STUDENT_NOT_ENROLLED, f"student {sid} is not ENROLLED")
        h = to_int(hours, "participant_hours value")
        if h < 0:
            raise_err(ERR_INVALID_REQUEST, "participant hours must be non-negative")
        participants.append((student, h))

    total_hours = sum(h for _, h in participants)
    if total_hours <= 0:
        raise_err(ERR_INVALID_REQUEST, "total participant hours must be positive")

    # Largest-remainder allocation
    raw = [(s, Decimal(raised_cents) * Decimal(h) / Decimal(total_hours), h)
           for s, h in participants]
    base = [(s, int(r.to_integral_value(rounding=ROUND_FLOOR)), r, h)
            for s, r, h in raw]
    distributed = sum(b for _, b, _, _ in base)
    remainder = raised_cents - distributed

    # Sort by frac DESC, tie-break student created_at ASC
    def _frac_key(item):
        s, b, r, h = item
        frac = r - Decimal(b)
        return (-frac, s["created_at"])

    sorted_parts = sorted(base, key=_frac_key)
    credits = {item[0]["id"]: item[1] for item in base}
    for i in range(remainder):
        sid = sorted_parts[i % len(sorted_parts)][0]["id"]
        credits[sid] += 1

    # Post FUNDRAISING_CREDIT rows
    total_allocated = 0
    for s, b, r, h in base:
        amount = credits[s["id"]]
        total_allocated += amount
        post_ledger(s["id"], "FUNDRAISING_CREDIT", amount, fundraiser_id=fid)

    f["raised_cents"] = raised_cents
    f["allocated_credit_cents"] = total_allocated
    f["status"] = "CREDITED"
    f["version"] += 1
    f["updated_at"] = now_iso()
    return success(fundraiser_out(f))
