"""Instrument + InstrumentAssignment endpoints."""
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt, days_ceil, ceil_div
from errors import (
    raise_err, ERR_INSTRUMENT_NOT_FOUND, ERR_INSTRUMENT_ASSIGNMENT_NOT_FOUND,
    ERR_STUDENT_NOT_FOUND, ERR_INSTRUMENT_NOT_AVAILABLE, ERR_INSTRUMENT_CHECKED_OUT,
    ERR_INSTRUMENT_RETIRED, ERR_ASSIGNMENT_NOT_ACTIVE, ERR_INSTRUMENT_UNPLAYABLE,
    ERR_DUE_DATE_INVALID, ERR_SERIAL_NUMBER_TAKEN, ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED,
    ERR_STUDENT_NOT_ENROLLED, ERR_STUDENT_DELINQUENT_FEES, ERR_REPAIR_BUDGET_EXCEEDED,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import instrument_out, instrument_assignment_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from services.ledger import post_ledger, round_half_up_cents
from routes.programs import _get_program_or_404, _program_posture_open
from routes.students import _get_student_or_404

bp = Blueprint("instruments", __name__)

CONDITIONS = ["EXCELLENT", "GOOD", "FAIR", "POOR", "UNPLAYABLE"]


def _get_instrument_or_404(iid):
    i = store.instruments.get(iid)
    if i is None:
        raise_err(ERR_INSTRUMENT_NOT_FOUND, f"instrument {iid} not found")
    return i


def _get_assignment_or_404(aid):
    a = store.instrument_assignments.get(aid)
    if a is None:
        raise_err(ERR_INSTRUMENT_ASSIGNMENT_NOT_FOUND, f"instrument assignment {aid} not found")
    return a


def _recompute_repair_spent(program_id):
    # repair_spent is tracked as a running total at complete-maintenance time
    # but we recompute it as sum of stored complete-maintenance repairs. We track
    # each completion by storing on instrument itself — simpler: store at completion
    # For now recompute via a list we maintain on program.
    pass


@bp.route("/band/instruments", methods=["POST"])
def create_instrument():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"program_id", "serial_number", "instrument_type",
                         "replacement_value_cents", "condition_grade"})
    require(data, "program_id", "serial_number", "instrument_type", "replacement_value_cents")
    pid = to_str(data["program_id"], "program_id")
    serial_number = to_str(data["serial_number"], "serial_number")
    instrument_type = to_str(data["instrument_type"], "instrument_type")
    replacement_value_cents = to_int(data["replacement_value_cents"], "replacement_value_cents")
    condition_grade = to_enum(data.get("condition_grade", "GOOD"), "condition_grade", set(CONDITIONS))

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    # serial unique per program
    for existing in store.instruments.values():
        if existing["program_id"] == pid and existing["serial_number"] == serial_number:
            raise_err(ERR_SERIAL_NUMBER_TAKEN, f"serial_number {serial_number} already exists in program")

    iid = new_id()
    now_s = now_iso()
    i = {
        "id": iid,
        "program_id": pid,
        "serial_number": serial_number,
        "instrument_type": instrument_type,
        "condition_grade": condition_grade,
        "replacement_value_cents": replacement_value_cents,
        "status": "AVAILABLE",
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.instruments[iid] = i
    return success(instrument_out(i), status=201)


@bp.route("/band/instruments", methods=["GET"])
def list_instruments():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.instruments.values())
    pid = request.args.get("program_id")
    if pid:
        items = [i for i in items if i["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [i for i in items if i["status"] == st]
    it = request.args.get("instrument_type")
    if it:
        items = [i for i in items if i["instrument_type"] == it]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([instrument_out(i) for i in page], is_list=True, pagination=pag)


@bp.route("/band/instruments/<iid>", methods=["GET"])
def get_instrument(iid):
    require_roles(["Any"])
    apply_time_transitions()
    i = _get_instrument_or_404(iid)
    return success(instrument_out(i))


@bp.route("/band/instruments/<iid>/retire", methods=["POST"])
def retire_instrument(iid):
    require_roles(["EquipmentManager"])
    i = _get_instrument_or_404(iid)
    if i["status"] == "RETIRED":
        raise_err(ERR_INSTRUMENT_RETIRED, "instrument already retired")
    if i["status"] == "CHECKED_OUT":
        raise_err(ERR_INSTRUMENT_CHECKED_OUT, "instrument is checked out")
    if i["status"] not in ("AVAILABLE", "IN_MAINTENANCE"):
        raise_err(ERR_INVALID_STATE, f"cannot retire instrument in {i['status']}")
    i["status"] = "RETIRED"
    i["version"] += 1
    i["updated_at"] = now_iso()
    return success(instrument_out(i))


@bp.route("/band/instruments/<iid>/complete-maintenance", methods=["POST"])
def complete_maintenance(iid):
    require_roles(["EquipmentManager"])
    i = _get_instrument_or_404(iid)
    data = body()
    check_unknown(data, {"repair_cost_cents"})
    require(data, "repair_cost_cents")
    repair_cost_cents = to_int(data["repair_cost_cents"], "repair_cost_cents")
    if repair_cost_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "repair_cost_cents must be positive")
    if i["status"] != "IN_MAINTENANCE":
        raise_err(ERR_INVALID_STATE, "instrument is not IN_MAINTENANCE")
    program = _get_program_or_404(i["program_id"])
    if program["repair_spent_cents"] + repair_cost_cents > program["repair_budget_cents"]:
        raise_err(ERR_REPAIR_BUDGET_EXCEEDED, "repair would exceed budget")
    program["repair_spent_cents"] += repair_cost_cents
    program["version"] += 1
    program["updated_at"] = now_iso()
    # restore condition to GOOD if degraded below GOOD
    if i["condition_grade"] in ("FAIR", "POOR", "UNPLAYABLE"):
        i["condition_grade"] = "GOOD"
    i["status"] = "AVAILABLE"
    i["version"] += 1
    i["updated_at"] = now_iso()
    return success(instrument_out(i))


# -------- InstrumentAssignment --------

def _compute_accrued_fee(fee_variant, checkout_at, due_date):
    """Return accrued_fee_cents for the variant."""
    if fee_variant == "FLAT":
        return 15000
    # PRORATED: ceil days, then ceil weeks (min 1)
    days = days_ceil(due_date, checkout_at)
    if days <= 0:
        days = 1
    weeks = max(1, ceil_div(days, 7))
    return weeks * 2000


@bp.route("/band/instrument-assignments", methods=["POST"])
def create_assignment():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"student_id", "instrument_id", "due_date"})
    require(data, "student_id", "instrument_id", "due_date")
    student_id = to_str(data["student_id"], "student_id")
    instrument_id = to_str(data["instrument_id"], "instrument_id")
    try:
        due_date = parse_dt(data["due_date"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "due_date must be ISO8601")

    student = _get_student_or_404(student_id)
    instrument = _get_instrument_or_404(instrument_id)

    # Program posture
    program = _get_program_or_404(student["program_id"])
    _program_posture_open(program)

    # State checks
    if student["enrollment_status"] != "ENROLLED":
        raise_err(ERR_STUDENT_NOT_ENROLLED, "student must be ENROLLED")
    if instrument["status"] != "AVAILABLE":
        raise_err(ERR_INSTRUMENT_NOT_AVAILABLE, "instrument is not AVAILABLE")

    # Business safety
    if instrument["condition_grade"] == "UNPLAYABLE":
        raise_err(ERR_INSTRUMENT_UNPLAYABLE, "instrument is UNPLAYABLE")

    # Temporal
    checkout_at = now()
    if due_date <= checkout_at:
        raise_err(ERR_DUE_DATE_INVALID, "due_date must be strictly after checkout")

    # Uniqueness: one ACTIVE/OVERDUE assignment per (student, instrument_type)
    for a in store.instrument_assignments.values():
        if a["student_id"] == student_id and a["status"] in ("ACTIVE", "OVERDUE"):
            other_instr = store.instruments.get(a["instrument_id"])
            if other_instr and other_instr["instrument_type"] == instrument["instrument_type"]:
                raise_err(ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED,
                          f"student already holds an active {instrument['instrument_type']} assignment")

    # Fiscal: delinquency gate
    if student["account_balance_cents"] > program["delinquency_grace_cents"]:
        raise_err(ERR_STUDENT_DELINQUENT_FEES, "student is delinquent")

    # Compute fee variant
    fee_variant = program["rental_fee_mode"]
    accrued_fee_cents = _compute_accrued_fee(fee_variant, checkout_at, due_date)

    aid = new_id()
    now_s = now_iso()
    a = {
        "id": aid,
        "student_id": student_id,
        "instrument_id": instrument_id,
        "status": "ACTIVE",
        "checkout_at": now_s,
        "due_date": due_date,
        "returned_at": None,
        "fee_variant": fee_variant,
        "accrued_fee_cents": accrued_fee_cents,
        "late_fee_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.instrument_assignments[aid] = a
    instrument["status"] = "CHECKED_OUT"
    instrument["version"] += 1
    instrument["updated_at"] = now_s
    # Post RENTAL_FEE_DEBIT
    post_ledger(student_id, "RENTAL_FEE_DEBIT", accrued_fee_cents)
    return success(instrument_assignment_out(a), status=201)


@bp.route("/band/instrument-assignments", methods=["GET"])
def list_assignments():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.instrument_assignments.values())
    sid = request.args.get("student_id")
    if sid:
        items = [a for a in items if a["student_id"] == sid]
    iid = request.args.get("instrument_id")
    if iid:
        items = [a for a in items if a["instrument_id"] == iid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([instrument_assignment_out(a) for a in page], is_list=True, pagination=pag)


@bp.route("/band/instrument-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles(["Any"])
    apply_time_transitions()
    a = _get_assignment_or_404(aid)
    return success(instrument_assignment_out(a))


@bp.route("/band/instrument-assignments/<aid>/return", methods=["POST"])
def return_assignment(aid):
    require_roles(["EquipmentManager"])
    apply_time_transitions()
    a = _get_assignment_or_404(aid)
    data = body()
    check_unknown(data, {"inspection_result"})
    require(data, "inspection_result")
    inspection_result = to_enum(data["inspection_result"], "inspection_result", {"PASS", "FAIL"})
    if a["status"] not in ("ACTIVE", "OVERDUE"):
        raise_err(ERR_ASSIGNMENT_NOT_ACTIVE, "assignment is not ACTIVE or OVERDUE")

    n = now()
    was_overdue = (a["status"] == "OVERDUE") or (n > a["due_date"])
    returned_at_s = now_iso()
    a["returned_at"] = returned_at_s
    a["status"] = "RETURNED"

    if was_overdue:
        days = days_ceil(n, a["due_date"])
        weeks = max(1, ceil_div(days, 7))
        late_fee = weeks * 500
        a["late_fee_cents"] = late_fee
        if late_fee > 0:
            post_ledger(a["student_id"], "LATE_FEE_DEBIT", late_fee)
    else:
        a["late_fee_cents"] = 0

    a["version"] += 1
    a["updated_at"] = now_iso()

    instr = store.instruments.get(a["instrument_id"])
    if instr:
        if inspection_result == "PASS":
            instr["status"] = "AVAILABLE"
        else:
            instr["status"] = "IN_MAINTENANCE"
            # degrade one step
            cur = instr["condition_grade"]
            ladder = ["EXCELLENT", "GOOD", "FAIR", "POOR", "UNPLAYABLE"]
            try:
                idx = ladder.index(cur)
            except ValueError:
                idx = 1  # default GOOD
            new_idx = min(idx + 1, len(ladder) - 1)
            instr["condition_grade"] = ladder[new_idx]
        instr["version"] += 1
        instr["updated_at"] = now_iso()

    return success(instrument_assignment_out(a))


@bp.route("/band/instrument-assignments/<aid>/renew", methods=["POST"])
def renew_assignment(aid):
    require_roles(["EquipmentManager"])
    apply_time_transitions()
    a = _get_assignment_or_404(aid)
    data = body()
    check_unknown(data, {"new_due_date"})
    require(data, "new_due_date")
    try:
        new_due_date = parse_dt(data["new_due_date"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "new_due_date must be ISO8601")
    if a["status"] not in ("ACTIVE", "OVERDUE"):
        raise_err(ERR_ASSIGNMENT_NOT_ACTIVE, "assignment is not ACTIVE or OVERDUE")
    if new_due_date <= a["due_date"]:
        raise_err(ERR_DUE_DATE_INVALID, "new_due_date must be strictly after current due_date")

    # PRORATED: recompute fee over (checkout_at → new_due_date) and post delta
    if a["fee_variant"] == "PRORATED":
        try:
            checkout_at = parse_dt(a["checkout_at"])
        except Exception:
            checkout_at = now()
        new_fee = _compute_accrued_fee("PRORATED", checkout_at, new_due_date)
        delta = new_fee - a["accrued_fee_cents"]
        if delta > 0:
            post_ledger(a["student_id"], "RENTAL_FEE_DEBIT", delta)
        a["accrued_fee_cents"] = new_fee

    a["due_date"] = new_due_date
    if a["status"] == "OVERDUE":
        a["status"] = "ACTIVE"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(instrument_assignment_out(a))
