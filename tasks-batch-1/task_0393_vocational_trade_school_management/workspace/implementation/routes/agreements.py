"""Routes for EnrollmentAgreement and its lifecycle transitions."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_role, ALL_ROLES
from helpers import (
    get_json_body, serialize, stamp_new, bump, paginate, sorted_collection,
    find_or_404, as_int, as_str,
)
from response import success
import services

bp = Blueprint("agreements", __name__)


def _serialize_agreement(a):
    return serialize(a)


@bp.post("/v1/enrollment-agreements")
def create_agreement():
    require_role(["Registrar"])
    body = get_json_body()
    student_id = as_str(body, "student_id", required=True)
    cohort_id = as_str(body, "cohort_id", required=True)
    contract_tuition = as_int(body, "contract_tuition_cents", required=True, minimum=0)
    # scheduled_aid validated after we know contract tuition
    cancellation_window = as_int(body, "cancellation_window_term_index", required=True)

    # Existence: body ids resolved in documented order (student, cohort).
    student = find_or_404(store.students, student_id, "Student")
    cohort = find_or_404(store.cohorts, cohort_id, "Cohort")

    scheduled_aid = as_int(body, "scheduled_aid_cents", required=False, minimum=0, default=0)
    if scheduled_aid > contract_tuition:
        raise err("ERR_INVALID_REQUEST",
                  "scheduled_aid_cents must be <= contract_tuition_cents.")
    if cancellation_window < cohort["start_term_index"]:
        raise err("ERR_INVALID_REQUEST",
                  "cancellation_window_term_index must be >= cohort.start_term_index.")

    # Scope: the cohort's program is the authoritative program scope. A draft is
    # rejected when cross-references resolve to an inconsistent program scope.
    program = store.programs.get(cohort["program_id"])
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found.")
    if "program_id" in body and body["program_id"] is not None:
        if body["program_id"] != cohort["program_id"]:
            raise err("ERR_SCOPE_MISMATCH",
                      "Provided program_id does not match the cohort's program.")

    agreement = {
        "student_id": student_id,
        "cohort_id": cohort_id,
        "program_id": cohort["program_id"],
        "contract_tuition_cents": contract_tuition,
        "scheduled_aid_cents": scheduled_aid,
        "cancellation_window_term_index": cancellation_window,
        "theory_hours_completed": 0,
        "externship_hours_completed": 0,
        "clock_hours_completed": 0,
        "scheduled_hours_to_date": 0,
        "attendance_pct": 1.0,
        "completion_pct": 0.0,
        "disbursed_aid_cents": 0,
        "ledger_balance_cents": contract_tuition,
        "sap_standing": "GOOD",
        "licensure_eligible": False,
        "status": "DRAFTED",
        "withdrawal_term_index": None,
    }
    stamp_new(agreement)
    store.enrollment_agreements[agreement["id"]] = agreement
    # Derive computed fields from empty ledger (sets attendance_pct=1.0, etc.).
    services.recompute_agreement(agreement)
    return success(_serialize_agreement(agreement), 201)


@bp.get("/v1/enrollment-agreements")
def list_agreements():
    require_role(ALL_ROLES)
    student_id = request.args.get("student_id")
    cohort_id = request.args.get("cohort_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")

    def pred(e):
        if student_id and e["student_id"] != student_id:
            return False
        if cohort_id and e["cohort_id"] != cohort_id:
            return False
        if program_id and e["program_id"] != program_id:
            return False
        if status and e["status"] != status:
            return False
        return True

    items = sorted_collection(store.enrollment_agreements, predicate=pred)
    page, meta = paginate(items)
    return success([_serialize_agreement(e) for e in page], 200, pagination=meta)


@bp.get("/v1/enrollment-agreements/<aid>")
def get_agreement(aid):
    require_role(ALL_ROLES)
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/enroll")
def enroll_agreement(aid):
    require_role(["Registrar"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] != "DRAFTED":
        raise err("ERR_INVALID_STATE", "Agreement must be DRAFTED to enroll.")
    student = store.students[a["student_id"]]
    if not student["hs_diploma_verified"]:
        raise err("ERR_ADMISSION_PREREQ_UNMET",
                  "Student high-school diploma is not verified.")
    cohort = store.cohorts[a["cohort_id"]]
    if cohort["status"] not in ("FORMING", "RUNNING"):
        raise err("ERR_COHORT_CLOSED", "Cohort is not accepting new enrollments.")
    if cohort["enrolled_count"] >= cohort["seat_capacity"]:
        raise err("ERR_COHORT_FULL", "Cohort has reached seat capacity.")

    a["status"] = "ENROLLED"
    cohort["enrolled_count"] += 1
    bump(cohort)
    services.recompute_agreement(a)
    bump(a)
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/cancel")
def cancel_agreement(aid):
    require_role(["Registrar"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] != "DRAFTED":
        raise err("ERR_INVALID_STATE", "Agreement must be DRAFTED to cancel.")
    a["status"] = "CANCELLED"
    bump(a)
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/start-loa")
def start_loa(aid):
    require_role(["AcademicAdvisor"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Agreement must be ENROLLED to start LOA.")
    if a["sap_standing"] == "DISMISSED":
        raise err("ERR_SAP_DISMISSED", "Agreement SAP standing is DISMISSED.")
    a["status"] = "LEAVE_OF_ABSENCE"
    bump(a)
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/return-from-loa")
def return_from_loa(aid):
    require_role(["AcademicAdvisor"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] != "LEAVE_OF_ABSENCE":
        raise err("ERR_INVALID_STATE", "Agreement must be LEAVE_OF_ABSENCE to return.")
    a["status"] = "ENROLLED"
    bump(a)
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/graduate")
def graduate_agreement(aid):
    require_role(["Registrar"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Agreement must be ENROLLED to graduate.")
    program = store.programs[a["program_id"]]
    if a["sap_standing"] not in ("GOOD", "WARNING"):
        raise err("ERR_SAP_NOT_SATISFACTORY",
                  "Graduation requires sap_standing in {GOOD, WARNING}.")
    # Compare hours with exact semantics (>=).
    from decimal import Decimal
    if Decimal(str(a["clock_hours_completed"])) < Decimal(str(program["required_clock_hours"])):
        raise err("ERR_CLOCK_HOURS_UNMET", "Clock hours below program minimum.")
    if Decimal(str(a["theory_hours_completed"])) < Decimal(str(program["required_theory_hours"])):
        raise err("ERR_THEORY_HOURS_UNMET", "Theory hours below program minimum.")
    if Decimal(str(a["externship_hours_completed"])) < Decimal(str(program["required_externship_hours"])):
        raise err("ERR_EXTERNSHIP_HOURS_UNMET", "Externship hours below program minimum.")
    if a["ledger_balance_cents"] > 0:
        raise err("ERR_BALANCE_OUTSTANDING", "Outstanding ledger balance.")

    a["status"] = "GRADUATED"
    services.recompute_agreement(a)
    bump(a)
    return success(_serialize_agreement(a), 200)


@bp.post("/v1/enrollment-agreements/<aid>/withdraw")
def withdraw_agreement(aid):
    require_role(["Registrar"])
    a = find_or_404(store.enrollment_agreements, aid, "EnrollmentAgreement")
    if a["status"] not in ("ENROLLED", "LEAVE_OF_ABSENCE"):
        raise err("ERR_INVALID_STATE",
                  "Agreement must be ENROLLED or LEAVE_OF_ABSENCE to withdraw.")
    services.cascade_withdraw(a)
    return success(_serialize_agreement(a), 200)
