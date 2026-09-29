"""Census, household enrollment and paid-claim evidence (sections 3.1, 3.9)."""

from flask import Blueprint

import auth
import calc
import clock
import constants as K
import db
import derive
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("employees", __name__)

ALL_ROLES = (
    "ProgramAdmin",
    "VerificationAnalyst",
    "AppealReviewer",
    "RecoveryAgent",
    "Employee",
)


def _employee_or_404(employee_id):
    employee = db.get("employees", employee_id)
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return employee


def _dependent_or_404(dependent_id):
    dependent = db.get("dependents", dependent_id)
    if dependent is None:
        raise ApiError("ERR_DEPENDENT_NOT_FOUND")
    return dependent


# ------------------------------------------------------------------ employees


@bp.route("/employees", methods=["POST"])
@endpoint("ProgramAdmin")
def create_employee():
    payload = validate.body()
    full_name = validate.req_str(payload, "full_name")
    work_email = validate.req_str(payload, "work_email")
    coverage_tier = validate.req_enum(payload, "coverage_tier", K.COVERAGE_TIERS)
    premium = validate.req_int(payload, "employer_monthly_premium_cents", minimum=0)
    hire_date = validate.req_date(payload, "hire_date")

    for existing in db.collection("employees").values():
        if existing["work_email"] == work_email:
            validate.bad("work_email is already registered to another employee.")

    employee = db.insert(
        "employees",
        {
            "full_name": full_name,
            "work_email": work_email,
            "coverage_tier": coverage_tier,
            "employer_monthly_premium_cents": premium,
            "hire_date": hire_date,
            "enrolled_dependent_count": 0,
        },
    )
    return response.obj_out(serialize.employee, employee, 201)


@bp.route("/employees/<employee_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_employee(employee_id):
    employee = _employee_or_404(employee_id)
    auth.require_employee_id(employee["id"])
    return response.obj_out(serialize.employee, employee)


# ------------------------------------------------------------------ dependents


@bp.route("/employees/<employee_id>/dependents", methods=["POST"])
@endpoint("ProgramAdmin", "Employee")
def enroll_dependent(employee_id):
    employee = _employee_or_404(employee_id)
    auth.require_employee_id(employee["id"])

    payload = validate.body()
    relationship_type = validate.req_enum(
        payload, "relationship_type", K.RELATIONSHIP_TYPES
    )
    full_name = validate.req_str(payload, "full_name")
    date_of_birth = validate.req_date(payload, "date_of_birth")
    # monthly_cost_cents is accepted but never persisted: the schedule wins.
    validate.opt_int(payload, "monthly_cost_cents", minimum=0)
    explicit_program_id = validate.opt_str(payload, "poe_program_id")

    now = clock.now()
    program = None
    rule = None
    if explicit_program_id is not None:
        program = db.get("programs", explicit_program_id)
        if program is None:
            raise ApiError("ERR_PROGRAM_NOT_FOUND")
        rule = calc.find_rule(program["id"], relationship_type, "POINT_OF_ENROLLMENT")
        if rule is None:
            raise ApiError("ERR_DOCUMENTATION_RULE_MISSING")
    else:
        candidates = calc.poe_program_candidates(relationship_type, now)
        if calc.poe_selection_is_ambiguous(candidates):
            raise ApiError("ERR_POE_PROGRAM_AMBIGUOUS")
        if candidates:
            program, rule = candidates[0]

    fields = {
        "employee_id": employee["id"],
        "relationship_type": relationship_type,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "enrolled_at": clock.fmt_date(now.date()),
        "coverage_status": "ENROLLED",
        "coverage_end_date": None,
        "poe_program_id": None,
        "poe_deadline_at": None,
        "monthly_cost_cents": K.RELATIONSHIP_MONTHLY_COST_CENTS[relationship_type],
        "accepted_proof_type_count": 0,
        "documentation_complete": False,
        "recovery_revision": 0,
        "paid_claims_total_cents": 0,
        "reinstated_at": None,
    }
    if program is not None:
        fields["coverage_status"] = "PENDING_VERIFICATION"
        fields["poe_program_id"] = program["id"]
        fields["poe_deadline_at"] = clock.add_days_dt(now, rule["grace_days"])

    dependent = db.insert("dependents", fields)
    derive.refresh_all()
    return response.obj_out(serialize.dependent, dependent, 201)


@bp.route("/employees/<employee_id>/dependents", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_employee_dependents(employee_id):
    employee = _employee_or_404(employee_id)
    auth.require_employee_id(employee["id"])
    coverage_status = validate.query_filter("coverage_status")
    rows = db.ordered(
        "dependents",
        lambda d: d["employee_id"] == employee["id"]
        and (coverage_status is None or d["coverage_status"] == coverage_status),
    )
    return response.arr_out(serialize.dependent, rows, validate.paginate(rows))


@bp.route("/dependents/<dependent_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_dependent(dependent_id):
    dependent = _dependent_or_404(dependent_id)
    auth.require_owns_dependent(dependent)
    return response.obj_out(serialize.dependent, dependent)


# ------------------------------------------------------------------ paid claims


@bp.route("/dependents/<dependent_id>/paid-claims", methods=["POST"])
@endpoint("ProgramAdmin", "RecoveryAgent")
def record_paid_claim(dependent_id):
    dependent = _dependent_or_404(dependent_id)
    payload = validate.body()
    service_date = validate.req_date(payload, "service_date")
    paid_cents = validate.req_int(payload, "paid_cents", minimum=1)
    offset_cents = validate.opt_int(
        payload, "employee_premium_offset_cents", default=0, minimum=0
    )
    claim_reference = validate.req_str(payload, "claim_reference")
    provider_type = validate.opt_enum(payload, "provider_type", K.PROVIDER_TYPES)

    line = db.insert(
        "claim_lines",
        {
            "dependent_id": dependent["id"],
            "service_date": service_date,
            "paid_cents": paid_cents,
            "employee_premium_offset_cents": offset_cents,
            "claim_reference": claim_reference,
            "provider_type": provider_type,
        },
    )
    derive.refresh_all()
    return response.obj_out(serialize.claim_line, line, 201)


@bp.route("/dependents/<dependent_id>/paid-claims", methods=["GET"])
@endpoint("ProgramAdmin", "RecoveryAgent", "VerificationAnalyst")
def list_paid_claims(dependent_id):
    dependent = _dependent_or_404(dependent_id)
    rows = db.ordered("claim_lines", lambda l: l["dependent_id"] == dependent["id"])
    return response.arr_out(serialize.claim_line, rows, validate.paginate(rows))


@bp.route("/dependents/<dependent_id>/amnesty-removals", methods=["GET"])
@endpoint("ProgramAdmin", "VerificationAnalyst", "RecoveryAgent", "Employee")
def list_dependent_amnesty_removals(dependent_id):
    dependent = _dependent_or_404(dependent_id)
    auth.require_owns_dependent(dependent)
    rows = db.ordered(
        "amnesty_removals", lambda r: r["dependent_id"] == dependent["id"]
    )
    return response.arr_out(serialize.amnesty_removal, rows, validate.paginate(rows))
