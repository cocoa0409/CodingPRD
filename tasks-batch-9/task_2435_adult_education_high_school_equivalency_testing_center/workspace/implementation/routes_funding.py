"""Credentials, transcript orders, outcome measures, funding and the clock."""

from decimal import Decimal

from flask import Blueprint, request

import calc
from core import (
    auth,
    body,
    by_created,
    clock,
    created,
    deny_scope,
    find_credential,
    find_outcome,
    find_period,
    find_student,
    find_transcript,
    fmt_clock,
    new_record,
    ok,
    opt_enum,
    opt_fk,
    pagination,
    paginate,
    parse_date,
    pub,
    req_date,
    req_dt,
    req_enum,
    req_fk,
    req_int,
    req_str,
    set_clock,
    store,
    touch,
)
from errors import ApiError

bp = Blueprint("funding", __name__)

CLOCK_WRITE_ROLES = ("StateAuthority", "ProgramCoordinator", "Registrar",
                     "CenterAdministrator", "Instructor")
DELIVERY_SPEEDS = ("STANDARD", "RUSH")
DESTINATION_TYPES = ("SELF", "EMPLOYER", "POSTSECONDARY", "STATE_RECORDS")


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

@bp.post("/credentials")
def issue_credential():
    auth("StateAuthority")
    data = body()
    student_id = req_fk(data, "student_id")
    credential_type = opt_enum(data, "credential_type", ("HSE_DIPLOMA",),
                               default="HSE_DIPLOMA")
    student = find_student(student_id)

    for existing in store.credentials.values():
        if existing["student_id"] == student["id"] and existing["status"] == "ISSUED":
            raise ApiError("ERR_DUPLICATE_CREDENTIAL")

    result = calc.credential_eligibility(student["id"])
    if not result["eligible"]:
        raise ApiError("ERR_CREDENTIAL_REQUIREMENTS_NOT_MET")

    credential = new_record(store.credentials, {
        "student_id": student["id"],
        "credential_type": credential_type,
        "composite_score": result["composite_score"],
        "subtest_scores": result["subtest_scores"],
        "qualifying_registration_ids": result["qualifying_registration_ids"],
        "status": "ISSUED",
        "issued_at": fmt_clock(clock()),
        "void_reason": None,
    })

    student["credential_status"] = "ISSUED"
    if student["active_enrollment_count"] == 0:
        student["intake_status"] = "EXITED"
    touch(student)

    return created(pub(credential))


@bp.get("/credentials/<credential_id>")
def read_credential(credential_id):
    role, user_id = auth("StateAuthority", "ProgramCoordinator", "Student")
    credential = find_credential(credential_id)
    if role == "Student" and user_id != credential["student_id"]:
        deny_scope()
    return ok(pub(credential))


@bp.get("/credentials")
def list_credentials():
    auth("StateAuthority", "ProgramCoordinator")
    limit, offset = pagination()
    rows = list(store.credentials.values())
    for key in ("student_id", "status", "credential_type"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# transcript orders
# --------------------------------------------------------------------------

@bp.post("/students/<student_id>/transcript-orders")
def order_transcript(student_id):
    role, user_id = auth("Student", "Registrar")
    student = find_student(student_id)
    if role == "Student" and user_id != student["id"]:
        deny_scope()

    data = body()
    credential_id = req_fk(data, "credential_issuance_id")
    copies = req_int(data, "copies", minimum=1, maximum=10)
    delivery = req_enum(data, "delivery", DELIVERY_SPEEDS)
    destination_type = req_enum(data, "destination_type", DESTINATION_TYPES)

    credential = find_credential(credential_id)
    if credential["status"] != "ISSUED":
        raise ApiError("ERR_CREDENTIAL_NOT_ISSUED")

    charge = calc.transcript_charge(copies, delivery)
    order = new_record(store.transcripts, {
        "student_id": student["id"],
        "credential_issuance_id": credential["id"],
        "copies": copies,
        "delivery": delivery,
        "destination_type": destination_type,
        "base_charge_cents": charge["base_charge_cents"],
        "waiver_cents": charge["waiver_cents"],
        "state_records_fee_cents": charge["state_records_fee_cents"],
        "total_charge_cents": charge["total_charge_cents"],
        "status": "QUEUED",
        "fulfilled_at": None,
        "hold_reason": None,
    })
    return created(pub(order))


@bp.post("/transcript-orders/<order_id>/fulfillment")
def fulfill_transcript(order_id):
    auth("Registrar", "ProgramCoordinator")
    order = find_transcript(order_id)
    if order["status"] != "QUEUED":
        raise ApiError("ERR_TRANSCRIPT_ORDER_NOT_QUEUED")
    credential = store.credentials.get(order["credential_issuance_id"])
    if credential is None or credential["status"] != "ISSUED":
        raise ApiError("ERR_CREDENTIAL_NOT_ISSUED")
    order["status"] = "FULFILLED"
    order["fulfilled_at"] = fmt_clock(clock())
    touch(order)
    return ok(pub(order))


@bp.get("/transcript-orders/<order_id>")
def read_transcript(order_id):
    role, user_id = auth("ProgramCoordinator", "StateAuthority", "Student")
    order = find_transcript(order_id)
    if role == "Student" and user_id != order["student_id"]:
        deny_scope()
    return ok(pub(order))


@bp.get("/transcript-orders")
def list_transcripts():
    auth("ProgramCoordinator", "StateAuthority")
    limit, offset = pagination()
    rows = list(store.transcripts.values())
    for key in ("student_id", "credential_issuance_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# outcome records
# --------------------------------------------------------------------------

@bp.post("/outcome-records")
def record_outcome():
    role, user_id = auth("ProgramCoordinator", "StateAuthority")
    data = body()
    student_id = req_fk(data, "student_id")
    period_id = req_fk(data, "funding_period_id")
    measure_type = req_enum(data, "measure_type", calc.MEASURE_TYPES)
    evidence_ref = req_str(data, "evidence_ref")
    credential_id = opt_fk(data, "credential_issuance_id")

    student = find_student(student_id)
    period = find_period(period_id)
    credential = find_credential(credential_id) if credential_id is not None else None

    if measure_type == "CREDENTIAL_ATTAINMENT" and credential is not None:
        if credential["status"] != "ISSUED":
            raise ApiError("ERR_CREDENTIAL_NOT_ISSUED")

    if period["status"] != "OPEN":
        raise ApiError("ERR_FUNDING_PERIOD_CLOSED")

    if measure_type == "CREDENTIAL_ATTAINMENT":
        if credential is None or credential["student_id"] != student["id"]:
            raise ApiError("ERR_OUTCOME_EVIDENCE_MISMATCH")
    else:
        credential = None

    outcome = new_record(store.outcomes, {
        "student_id": student["id"],
        "funding_period_id": period["id"],
        "credential_issuance_id": credential["id"] if credential else None,
        "measure_type": measure_type,
        "evidence_ref": evidence_ref,
        "status": "RECORDED",
        "recorded_by_user_id": user_id,
        "certified_by_user_id": None,
        "weight": float(calc.MEASURE_WEIGHT[measure_type]),
        "allocated_cents": 0,
        "allocation_status": "UNALLOCATED",
        "rescission_reason": None,
    })
    return created(pub(outcome))


@bp.post("/outcome-records/<outcome_id>/certification")
def certify_outcome(outcome_id):
    role, user_id = auth("StateAuthority", "ProgramCoordinator")
    outcome = find_outcome(outcome_id)
    data = body()
    decision = req_enum(data, "decision", ("CERTIFY", "REJECT"))

    if outcome["status"] != "RECORDED":
        raise ApiError("ERR_OUTCOME_NOT_CERTIFIABLE")

    period = store.periods.get(outcome["funding_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_FUNDING_PERIOD_CLOSED")

    if user_id == outcome["recorded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "CERTIFY":
        if outcome["measure_type"] == "EFL_GAIN":
            result = calc.msg_determination(outcome["student_id"], "LATEST_POST", period)
            if not result["msg_achieved"]:
                raise ApiError("ERR_MSG_NOT_SUPPORTED")
        if outcome["measure_type"] == "CREDENTIAL_ATTAINMENT":
            credential = store.credentials.get(outcome["credential_issuance_id"])
            if credential is None or credential["status"] != "ISSUED":
                raise ApiError("ERR_CREDENTIAL_NOT_ISSUED")
        outcome["status"] = "CERTIFIED"
    else:
        outcome["status"] = "REJECTED"

    outcome["certified_by_user_id"] = user_id
    touch(outcome)
    return ok(pub(outcome))


@bp.get("/outcome-records/<outcome_id>")
def read_outcome(outcome_id):
    auth("StateAuthority", "ProgramCoordinator", "Registrar")
    return ok(pub(find_outcome(outcome_id)))


@bp.get("/outcome-records")
def list_outcomes():
    auth("StateAuthority", "ProgramCoordinator", "Registrar")
    limit, offset = pagination()
    rows = list(store.outcomes.values())
    for key in ("student_id", "funding_period_id", "credential_issuance_id",
                "measure_type", "status", "allocation_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# funding periods
# --------------------------------------------------------------------------

@bp.post("/funding-periods")
def open_period():
    auth("StateAuthority")
    data = body()
    label = req_str(data, "label")
    start_raw, start_date = req_date(data, "start_date")
    end_raw, end_date = req_date(data, "end_date")
    if end_date <= start_date:
        raise ApiError("ERR_INVALID_REQUEST")
    rate = req_int(data, "rate_cents_per_weight", minimum=1)
    total = req_int(data, "total_cents", minimum=0)

    period = new_record(store.periods, {
        "label": label,
        "start_date": start_raw,
        "end_date": end_raw,
        "rate_cents_per_weight": rate,
        "total_cents": total,
        "committed_cents": 0,
        "available_cents": total,
        "allocation_run_count": 0,
        "last_allocation_run_at": None,
        "last_allocation_variant": None,
        "status": "OPEN",
    })
    return created(pub(period))


@bp.post("/funding-periods/<period_id>/allocation-run")
def allocation_run(period_id):
    auth("StateAuthority")
    period = find_period(period_id)
    data = body()
    variant = req_enum(data, "variant", calc.ALLOCATION_VARIANTS)
    expected = req_int(data, "expected_funding_period_version")

    if expected != period["version"]:
        raise ApiError("ERR_STALE_FUNDING_PERIOD_VERSION")
    if period["status"] != "OPEN":
        raise ApiError("ERR_FUNDING_PERIOD_CLOSED")

    lines, committed_total, deferred, total_weight = calc.allocation_walk(period, variant)
    for outcome, amount, posture in lines:
        outcome["allocated_cents"] = amount
        outcome["allocation_status"] = posture
        touch(outcome)

    period["committed_cents"] += committed_total
    period["available_cents"] = period["total_cents"] - period["committed_cents"]
    period["allocation_run_count"] += 1
    period["last_allocation_run_at"] = fmt_clock(clock())
    period["last_allocation_variant"] = variant
    touch(period)
    return ok(pub(period))


@bp.post("/funding-periods/<period_id>/close")
def close_period(period_id):
    auth("StateAuthority")
    period = find_period(period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_FUNDING_PERIOD_CLOSED")
    period["status"] = "CLOSED"
    touch(period)
    return ok(pub(period))


@bp.get("/funding-periods/<period_id>")
def read_period(period_id):
    auth("StateAuthority", "ProgramCoordinator")
    return ok(pub(find_period(period_id)))


@bp.get("/funding-periods")
def list_periods():
    auth("StateAuthority", "ProgramCoordinator")
    limit, offset = pagination()
    rows = list(store.periods.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(by_created(rows), limit, offset)


@bp.get("/funding-periods/<period_id>/allocation-preview")
def allocation_preview(period_id):
    auth("StateAuthority", "ProgramCoordinator")
    period = find_period(period_id)
    variant = request.args.get("variant")
    if variant is None:
        variant = "FINAL"
    elif variant not in calc.ALLOCATION_VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST")

    lines, committed_total, deferred, total_weight = calc.allocation_walk(period, variant)
    projected_committed = period["committed_cents"] + committed_total
    return ok({
        "funding_period_id": period["id"],
        "variant": variant,
        "total_weight": float(total_weight),
        "line_count": len(lines),
        "projected_committed_cents": projected_committed,
        "projected_available_cents": period["total_cents"] - projected_committed,
        "deferred_line_count": deferred,
    })


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(*CLOCK_WRITE_ROLES)
    data = body()
    raw, parsed = req_dt(data, "current_utc")
    if parsed < clock():
        raise ApiError("ERR_CLOCK_BACKWARD")
    set_clock(parsed)
    return ok({"current_utc": fmt_clock(parsed)})


@bp.get("/_clock/current_utc")
def get_current_utc():
    auth(*("StateAuthority", "ProgramCoordinator", "Registrar",
           "CenterAdministrator", "Instructor", "Proctor", "Student"))
    return ok({"current_utc": fmt_clock(clock())})
