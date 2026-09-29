"""Academic terms, departments, stipend policies and pay periods."""
from flask import Blueprint

import calc
import serialize
import validate as v
from db import db, insert, update, now_iso, iso
from errors import ApiError
from middleware import authenticate
from response import ok, created, ok_list
from services import effects, queries

bp = Blueprint("terms", __name__)

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant", "FacultySupervisor"]
SESSION_TYPES = ("IN_SESSION", "BREAK")
PRORATION_METHODS = ("CALENDAR_DAY", "WORKDAY")
ASSISTANTSHIP_TYPES = ("TEACHING", "RESEARCH", "ADMINISTRATIVE")
DEGREE_LEVELS = ("MASTERS", "DOCTORAL")
PAY_PERIOD_STATUSES = ("OPEN", "LOCKED", "CLOSED")


# ---------------------------------------------------------------------------
# AcademicTerm
# ---------------------------------------------------------------------------
@bp.post("/academic-terms")
def create_term():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    term_code = v.field_str(body, "term_code", min_len=1, max_len=32)
    term_start = v.field_date(body, "term_start")
    term_end = v.field_date(body, "term_end")
    tax_calendar_year = v.field_int(body, "tax_calendar_year", minimum=2000, maximum=2100)
    session_type = v.field_enum(body, "session_type", SESSION_TYPES)
    proration_method = v.field_enum(body, "proration_method", PRORATION_METHODS)
    remission_drop_deadline = v.field_date(body, "remission_drop_deadline")
    if term_end < term_start:
        raise v.invalid("term_end must be on or after term_start")
    if not (term_start <= remission_drop_deadline <= term_end):
        raise v.invalid("remission_drop_deadline must fall inside [term_start, term_end]")

    for row in db.academic_terms.values():
        if row["term_code"] == term_code:
            raise ApiError("ERR_DUPLICATE_TERM_CODE",
                           "term_code %s is already used" % term_code)

    row = insert(db.academic_terms, {
        "term_code": term_code,
        "term_start": term_start.isoformat(),
        "term_end": term_end.isoformat(),
        "tax_calendar_year": tax_calendar_year,
        "session_type": session_type,
        "proration_method": proration_method,
        "remission_drop_deadline": remission_drop_deadline.isoformat(),
        "status": "PLANNING",
        "pay_period_count": 0,
        "locked_at": None,
        "closed_at": None,
    })
    return created(serialize.term(row))


@bp.get("/academic-terms/<term_id>")
def read_term(term_id):
    authenticate(READ_ROLES)
    term = queries.term_or_404(term_id)
    return ok(serialize.term(term))


@bp.post("/academic-terms/<term_id>/open")
def open_term(term_id):
    authenticate(["GradSchoolAdmin"])
    term = queries.term_or_404(term_id)
    if term["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "Term must be PLANNING to open, not %s" % term["status"])
    periods = queries.pay_periods_of_term(term_id)
    policies = queries.policies_of_term(term_id)
    if len(periods) < 1 or len(policies) < 1:
        raise ApiError("ERR_TERM_CALENDAR_INCOMPLETE",
                       "A term requires at least one pay period and one stipend policy")
    update(term, status="OPEN", pay_period_count=len(periods))
    return ok(serialize.term(term))


@bp.post("/academic-terms/<term_id>/lock-payroll")
def lock_payroll(term_id):
    authenticate(["GradSchoolAdmin"])
    term = queries.term_or_404(term_id)
    if term["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "Term must be OPEN to lock payroll, not %s" % term["status"])
    for appointment in queries.appointments_of_term(term_id):
        if appointment["lifecycle_status"] == "FUNDING_VERIFIED":
            raise ApiError("ERR_UNRESOLVED_APPOINTMENTS",
                           "An appointment of the term is still FUNDING_VERIFIED")
    update(term, status="PAYROLL_LOCKED", locked_at=now_iso())
    for period in sorted(queries.pay_periods_of_term(term_id),
                         key=lambda p: (p["sequence_no"], p["_seq"])):
        if period["status"] == "OPEN":
            update(period, status="LOCKED")
    return ok(serialize.term(term))


@bp.post("/academic-terms/<term_id>/close")
def close_term(term_id):
    authenticate(["GradSchoolAdmin"])
    term = queries.term_or_404(term_id)
    if term["status"] != "PAYROLL_LOCKED":
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "Term must be PAYROLL_LOCKED to close, not %s" % term["status"])
    for disbursement in queries.disbursements_of_term(term_id):
        if disbursement["status"] not in ("PAID", "VOIDED", "REVERSED"):
            raise ApiError("ERR_UNSETTLED_DISBURSEMENTS",
                           "A disbursement of the term is still %s" % disbursement["status"])
    for assessment in queries.assessments_of_term(term_id):
        if assessment["status"] not in ("FINAL", "SUPERSEDED"):
            raise ApiError("ERR_UNSETTLED_DISBURSEMENTS",
                           "A tax assessment of the term is still %s" % assessment["status"])
    update(term, status="CLOSED", closed_at=now_iso())
    effects.close_term_cascade(term)
    return ok(serialize.term(term))


@bp.get("/academic-terms/<term_id>/stipend-policies")
def list_term_policies(term_id):
    authenticate(READ_ROLES)
    queries.term_or_404(term_id)
    assistantship_type = v.query_enum("assistantship_type", ASSISTANTSHIP_TYPES)
    degree_level = v.query_enum("degree_level", DEGREE_LEVELS)
    rows = queries.policies_of_term(term_id)
    if assistantship_type:
        rows = [r for r in rows if r["assistantship_type"] == assistantship_type]
    if degree_level:
        rows = [r for r in rows if r["degree_level"] == degree_level]
    page, meta = v.paginate(queries.by_created(rows))
    return ok_list([serialize.policy(r) for r in page], meta)


@bp.get("/academic-terms/<term_id>/pay-periods")
def list_term_pay_periods(term_id):
    authenticate(READ_ROLES)
    queries.term_or_404(term_id)
    status = v.query_enum("status", PAY_PERIOD_STATUSES)
    rows = queries.pay_periods_of_term(term_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["sequence_no"], r["_seq"]))
    page, meta = v.paginate(rows)
    return ok_list([serialize.pay_period(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------
@bp.post("/departments")
def create_department():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    code = v.field_str(body, "code", min_len=1, max_len=16)
    name = v.field_str(body, "name")
    notice_days = v.field_int(body, "non_renewal_notice_days", required=False,
                              default=60, minimum=1, maximum=180)
    row = insert(db.departments, {
        "code": code,
        "name": name,
        "non_renewal_notice_days": notice_days,
    })
    return created(serialize.department(row))


@bp.get("/departments/<department_id>")
def read_department(department_id):
    authenticate(READ_ROLES)
    department = queries.department_or_404(department_id)
    return ok(serialize.department(department))


# ---------------------------------------------------------------------------
# StipendPolicy
# ---------------------------------------------------------------------------
@bp.post("/stipend-policies")
def create_policy():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    term_ref = v.ref_value(body, "term_id")
    if term_ref is not None:
        term = queries.term_or_404(term_ref)
    else:
        term = None

    term_id = v.field_id(body, "term_id")
    assistantship_type = v.field_enum(body, "assistantship_type", ASSISTANTSHIP_TYPES)
    degree_level = v.field_enum(body, "degree_level", DEGREE_LEVELS)
    min_fte = v.field_int(body, "min_fte_monthly_stipend_cents", minimum=1)
    per_credit = v.field_int(body, "per_credit_tuition_cents", minimum=1)
    max_remission = v.field_int(body, "max_remission_cents_per_term", minimum=1)
    premium = v.field_int(body, "term_insurance_premium_cents", minimum=0)
    insurance_min_effort = v.field_int(body, "insurance_min_effort_pct", required=False,
                                      default=50, minimum=1, maximum=100)
    min_duration = v.field_int(body, "min_insurance_duration_days", required=False,
                              default=90, minimum=1)
    exempt_cap = v.field_int(body, "tuition_tax_exempt_cap_cents", required=False,
                             default=525000, minimum=0)

    if queries.find_policy(term_id, assistantship_type, degree_level) is not None:
        raise ApiError("ERR_DUPLICATE_STIPEND_POLICY",
                       "A stipend policy already exists for this term, type and degree level")

    if term["status"] not in ("PLANNING", "OPEN"):
        raise ApiError("ERR_TERM_NOT_OPEN",
                       "Term must be PLANNING or OPEN to declare a stipend policy")

    row = insert(db.stipend_policies, {
        "term_id": term_id,
        "assistantship_type": assistantship_type,
        "degree_level": degree_level,
        "min_fte_monthly_stipend_cents": min_fte,
        "insurance_min_effort_pct": insurance_min_effort,
        "min_insurance_duration_days": min_duration,
        "per_credit_tuition_cents": per_credit,
        "max_remission_cents_per_term": max_remission,
        "term_insurance_premium_cents": premium,
        "tuition_tax_exempt_cap_cents": exempt_cap,
    })
    return created(serialize.policy(row))


# ---------------------------------------------------------------------------
# PayPeriod
# ---------------------------------------------------------------------------
@bp.post("/pay-periods")
def create_pay_period():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    term_ref = v.ref_value(body, "term_id")
    term = queries.term_or_404(term_ref) if term_ref is not None else None

    term_id = v.field_id(body, "term_id")
    sequence_no = v.field_int(body, "sequence_no", minimum=1, maximum=24)
    period_start = v.field_date(body, "period_start")
    period_end_exclusive = v.field_date(body, "period_end_exclusive")
    pay_date = v.field_date(body, "pay_date")
    if period_end_exclusive <= period_start:
        raise v.invalid("period_end_exclusive must be strictly after period_start")
    if pay_date < period_end_exclusive:
        raise v.invalid("pay_date must be on or after period_end_exclusive")

    existing = queries.pay_periods_of_term(term_id)
    for row in existing:
        if row["sequence_no"] == sequence_no:
            raise ApiError("ERR_DUPLICATE_PAY_PERIOD_SEQUENCE",
                           "sequence_no %s already exists in this term" % sequence_no)

    if term["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "Pay periods may only be appended while the term is PLANNING")

    new_start = period_start.isoformat()
    new_end = period_end_exclusive.isoformat()
    for row in existing:
        if new_start < row["period_end_exclusive"] and row["period_start"] < new_end:
            raise ApiError("ERR_PAY_PERIOD_OVERLAP",
                           "The new pay period overlaps an existing period of the term")

    row = insert(db.pay_periods, {
        "term_id": term_id,
        "sequence_no": sequence_no,
        "period_start": new_start,
        "period_end_exclusive": new_end,
        "pay_date": pay_date.isoformat(),
        "calendar_day_count": calc.calendar_days(period_start, period_end_exclusive),
        "workday_count": calc.workdays(period_start, period_end_exclusive),
        "status": "OPEN",
    })
    update(term, pay_period_count=len(queries.pay_periods_of_term(term_id)))
    return created(serialize.pay_period(row))
