"""Program governance: creation, policy, scope, announcement, sweep, close."""

from flask import Blueprint

import calc
import clock
import constants as K
import db
import derive
import emit
import response
import serialize
import sweep
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("programs", __name__)

READ_ROLES = ("ProgramAdmin", "VerificationAnalyst", "AppealReviewer", "RecoveryAgent")


def _program_or_404(program_id):
    program = db.get("programs", program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return program


def _cases_of(program):
    return db.ordered("cases", lambda c: c["program_id"] == program["id"])


# ------------------------------------------------------------------ programs


@bp.route("/audit-programs", methods=["POST"])
@endpoint("ProgramAdmin")
def create_program():
    payload = validate.body()
    program_name = validate.req_str(payload, "program_name", min_len=1, max_len=120)
    plan_year = validate.req_int(payload, "plan_year", minimum=2020, maximum=2100)
    amnesty_days = validate.opt_int(payload, "amnesty_days", 21, 0, 90)
    response_days = validate.opt_int(payload, "response_days", 45, 7, 180)
    reminder_min_gap_days = validate.opt_int(
        payload, "reminder_min_gap_days", 7, 1, 60
    )
    max_reminders = validate.opt_int(payload, "max_reminders", 3, 1, 10)
    poe_enabled = validate.opt_bool(payload, "poe_verification_enabled", True)

    for existing in db.collection("programs").values():
        if (
            existing["plan_year"] == plan_year
            and existing["program_name"] == program_name
        ):
            raise ApiError("ERR_DUPLICATE_PROGRAM")

    program = db.insert(
        "programs",
        {
            "program_name": program_name,
            "plan_year": plan_year,
            "scope_type": None,
            "status": "DRAFT",
            "amnesty_days": amnesty_days,
            "response_days": response_days,
            "reminder_min_gap_days": reminder_min_gap_days,
            "max_reminders": max_reminders,
            "poe_verification_enabled": poe_enabled,
            "announcement_at": None,
            "amnesty_end_at": None,
            "response_deadline_at": None,
            "sweep_epoch": 0,
            "in_scope_case_count": 0,
            "in_scope_dependent_count": 0,
            "pending_dependent_count": 0,
            "verified_dependent_count": 0,
            "amnesty_removed_count": 0,
            "termination_pending_count": 0,
            "terminated_dependent_count": 0,
            "responded_case_count": 0,
            "non_responsive_case_count": 0,
            "provisional_annual_savings_cents": 0,
            "audited_annual_savings_cents": 0,
            "last_savings_variant": None,
            "recovery_ledger_cents": 0,
            "recovered_total_cents": 0,
            "refund_due_total_cents": 0,
        },
    )
    return response.obj_out(serialize.program, program, 201)


@bp.route("/audit-programs/<program_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_program(program_id):
    program = _program_or_404(program_id)
    return response.obj_out(serialize.program, program)


@bp.route("/audit-programs", methods=["GET"])
@endpoint(*READ_ROLES)
def list_programs():
    status = validate.query_filter("status")
    plan_year = validate.query_filter("plan_year")
    rows = db.ordered(
        "programs",
        lambda p: (status is None or p["status"] == status)
        and (plan_year is None or str(p["plan_year"]) == plan_year),
    )
    return response.arr_out(serialize.program, rows, validate.paginate(rows))


# ------------------------------------------------------------------ doc rules


@bp.route("/audit-programs/<program_id>/documentation-rules", methods=["POST"])
@endpoint("ProgramAdmin")
def create_documentation_rule(program_id):
    program = _program_or_404(program_id)
    payload = validate.body()
    relationship_type = validate.req_enum(
        payload, "relationship_type", K.RELATIONSHIP_TYPES
    )
    phase = validate.req_enum(payload, "phase", K.DOC_PHASES)
    acceptable = validate.req_str_list(
        payload, "acceptable_proof_types", K.PROOF_TYPES, min_items=1
    )
    min_accepted = validate.req_int(
        payload, "min_accepted_documents", minimum=1, maximum=5
    )
    affidavit_allowed = validate.opt_bool(payload, "affidavit_allowed", False)
    recency_days = validate.opt_int(payload, "requires_recency_days", 365, 30, 1095)
    grace_days = validate.opt_int(payload, "grace_days", None, 1, 180)
    auto_terminate = validate.opt_bool(payload, "auto_terminate_on_lapse", False)

    if phase == "POINT_OF_ENROLLMENT" and grace_days is None:
        raise ApiError("ERR_DOCUMENTATION_RULE_CONFLICT")
    if phase == "AUDIT" and grace_days is not None:
        raise ApiError("ERR_DOCUMENTATION_RULE_CONFLICT")
    if calc.find_rule(program["id"], relationship_type, phase) is not None:
        raise ApiError("ERR_DOCUMENTATION_RULE_CONFLICT")

    rule = db.insert(
        "doc_rules",
        {
            "program_id": program["id"],
            "relationship_type": relationship_type,
            "phase": phase,
            "acceptable_proof_types": list(acceptable),
            "min_accepted_documents": min_accepted,
            "affidavit_allowed": affidavit_allowed,
            "requires_recency_days": recency_days,
            "grace_days": grace_days,
            "auto_terminate_on_lapse": auto_terminate,
        },
    )
    return response.obj_out(serialize.doc_rule, rule, 201)


@bp.route("/audit-programs/<program_id>/documentation-rules", methods=["GET"])
@endpoint("ProgramAdmin", "VerificationAnalyst", "AppealReviewer")
def list_documentation_rules(program_id):
    program = _program_or_404(program_id)
    phase = validate.query_filter("phase")
    relationship_type = validate.query_filter("relationship_type")
    rows = db.ordered(
        "doc_rules",
        lambda r: r["program_id"] == program["id"]
        and (phase is None or r["phase"] == phase)
        and (relationship_type is None or r["relationship_type"] == relationship_type),
    )
    return response.arr_out(serialize.doc_rule, rows, validate.paginate(rows))


@bp.route("/audit-programs/<program_id>/dependents", methods=["GET"])
@endpoint("ProgramAdmin", "VerificationAnalyst")
def list_poe_dependents(program_id):
    program = _program_or_404(program_id)
    coverage_status = validate.query_filter("coverage_status")
    rows = db.ordered(
        "dependents",
        lambda d: d.get("poe_program_id") == program["id"]
        and (coverage_status is None or d["coverage_status"] == coverage_status),
    )
    return response.arr_out(serialize.dependent, rows, validate.paginate(rows))


# ------------------------------------------------------------------ scope run


@bp.route("/audit-programs/<program_id>/scope", methods=["POST"])
@endpoint("ProgramAdmin")
def run_scope(program_id):
    program = _program_or_404(program_id)
    payload = validate.body()
    expected_version = validate.req_int(payload, "expected_program_version")
    scope_type = validate.req_enum(payload, "scope_type", K.SCOPE_TYPES)
    targeted_ids = validate.opt_str_list(payload, "targeted_employee_ids")
    since_date = validate.opt_date(payload, "new_dependent_since_date")

    if program["status"] not in ("DRAFT", "SCOPED"):
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")

    if scope_type == "TARGETED":
        if not targeted_ids or since_date is not None:
            raise ApiError("ERR_SCOPE_PARAMETERS_INVALID")
    elif scope_type == "NEW_DEPENDENT_ONLY":
        if since_date is None or targeted_ids is not None:
            raise ApiError("ERR_SCOPE_PARAMETERS_INVALID")
    else:
        if targeted_ids is not None or since_date is not None:
            raise ApiError("ERR_SCOPE_PARAMETERS_INVALID")

    # A re-scope first voids the previous SELECTED case set, which returns those
    # dependents to ENROLLED. Selection is evaluated against that projected
    # census so the guards below can reject without having mutated anything.
    superseded = [c for c in _cases_of(program) if c["status"] == "SELECTED"]
    returning_ids = set()
    for case in superseded:
        returning_ids.update(case.get("in_scope_dependent_ids") or [])

    def is_enrolled(dependent):
        if dependent["coverage_status"] == "ENROLLED":
            return True
        return (
            dependent["id"] in returning_ids
            and dependent["coverage_status"] == "PENDING_VERIFICATION"
        )

    selection = calc.scope_candidate_selection(
        scope_type, targeted_ids, since_date, is_enrolled
    )

    missing = False
    for _employee, dependents in selection:
        for dependent in dependents:
            if calc.find_rule(program["id"], dependent["relationship_type"], "AUDIT") is None:
                missing = True
                break
        if missing:
            break
    if missing:
        raise ApiError("ERR_DOCUMENTATION_RULE_MISSING")

    if not selection:
        raise ApiError("ERR_SCOPE_EMPTY")

    for case in superseded:
        db.set_fields(case, status="VOIDED")
        for dep_id in case.get("in_scope_dependent_ids") or []:
            dependent = db.get("dependents", dep_id)
            if dependent is not None and dependent["coverage_status"] == "PENDING_VERIFICATION":
                db.set_fields(dependent, coverage_status="ENROLLED")

    for employee, dependents in selection:
        db.insert(
            "cases",
            {
                "program_id": program["id"],
                "employee_id": employee["id"],
                "status": "SELECTED",
                "in_scope_dependent_ids": [d["id"] for d in dependents],
                "in_scope_dependent_count": len(dependents),
                "unverified_dependent_count": 0,
                "proof_submission_count": 0,
                "reminders_sent_count": 0,
                "priority_score": 0,
                "notified_at": None,
                "last_reminder_at": None,
                "communication_sequence_no": 0,
                "non_responsive_at": None,
                "escalated_at": None,
                "completed_at": None,
            },
        )
        for dependent in dependents:
            db.set_fields(dependent, coverage_status="PENDING_VERIFICATION")

    db.set_fields(program, scope_type=scope_type, status="SCOPED")
    derive.refresh_all()
    db.mark_dirty(program)
    return response.obj_out(serialize.program, program)


# ------------------------------------------------------------------ announcement


@bp.route("/audit-programs/<program_id>/communicate", methods=["POST"])
@endpoint("ProgramAdmin")
def communicate(program_id):
    program = _program_or_404(program_id)
    payload = validate.body()
    channel = validate.req_enum(payload, "channel", K.CHANNELS)
    template_code = validate.opt_str(payload, "template_code")

    if program["status"] != "SCOPED":
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")
    selected = [c for c in _cases_of(program) if c["status"] == "SELECTED"]
    if not selected:
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")

    now = clock.now()
    window_start = now.date()
    window_end = clock.add_days(window_start, program["response_days"])
    blocking = ("NOTIFIED", "IN_PROGRESS", "NON_RESPONSIVE", "ESCALATED")
    for case in selected:
        for other in db.ordered(
            "cases", lambda c: c["employee_id"] == case["employee_id"]
        ):
            if other["id"] == case["id"] or other["status"] not in blocking:
                continue
            other_program = db.get("programs", other["program_id"])
            if other_program is None:
                continue
            announced = other_program.get("announcement_at")
            deadline = other_program.get("response_deadline_at")
            if announced is None or deadline is None:
                continue
            other_start = announced.date()
            other_end = deadline.date()
            if not (window_end < other_start or other_end < window_start):
                raise ApiError("ERR_CASE_WINDOW_OVERLAP")

    db.set_fields(
        program,
        status="AMNESTY_OPEN",
        announcement_at=now,
        amnesty_end_at=clock.add_days_dt(now, program["amnesty_days"]),
        response_deadline_at=clock.add_days_dt(now, program["response_days"]),
    )
    for case in selected:
        db.set_fields(case, status="NOTIFIED", notified_at=now)
        emit.communication(case, "ANNOUNCEMENT", channel, template_code, now)

    derive.refresh_all()
    return response.obj_out(serialize.program, program)


# ------------------------------------------------------------------ sweep


@bp.route("/audit-programs/<program_id>/run-sweep", methods=["POST"])
@endpoint("ProgramAdmin")
def run_sweep(program_id):
    program = _program_or_404(program_id)
    mutated = sweep.run(program)
    if mutated:
        derive.refresh_all()
        db.mark_dirty(program)
    return response.obj_out(serialize.program, program)


# ------------------------------------------------------------------ savings


@bp.route("/audit-programs/<program_id>/measure-savings", methods=["POST"])
@endpoint("ProgramAdmin")
def measure_savings(program_id):
    program = _program_or_404(program_id)
    payload = validate.body()
    variant = validate.req_enum(payload, "variant", K.SAVINGS_VARIANTS)

    figure = calc.savings(program, variant)
    if variant == "PROVISIONAL":
        db.set_fields(program, provisional_annual_savings_cents=figure)
    else:
        db.set_fields(program, audited_annual_savings_cents=figure)
    db.set_fields(program, last_savings_variant=variant)
    derive.refresh_all()
    return response.obj_out(serialize.program, program)


# ------------------------------------------------------------------ close


@bp.route("/audit-programs/<program_id>/close", methods=["POST"])
@endpoint("ProgramAdmin")
def close_program(program_id):
    program = _program_or_404(program_id)
    if program["status"] != "RECONCILIATION":
        raise ApiError("ERR_PROGRAM_PHASE_INVALID")

    cases = _cases_of(program)
    case_ids = set(c["id"] for c in cases)
    for appeal in db.collection("appeals").values():
        if appeal["case_id"] in case_ids and appeal["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "REMANDED",
        ):
            raise ApiError("ERR_OPEN_APPEALS_REMAIN")

    dependent_ids = set(calc.in_scope_dependent_ids(program))
    recoveries = [
        r
        for r in db.ordered("recoveries")
        if r["dependent_id"] in dependent_ids
    ]
    for recovery in recoveries:
        if recovery["status"] in ("DEMAND_ISSUED", "PARTIALLY_RECOVERED"):
            raise ApiError("ERR_OPEN_RECOVERIES_REMAIN")

    db.set_fields(program, status="CLOSED")
    for case in cases:
        if case["status"] == "COMPLETE":
            db.set_fields(case, status="CLOSED")
    for recovery in recoveries:
        if recovery["status"] == "OPEN":
            db.set_fields(recovery, status="WRITTEN_OFF")
    for submission in db.ordered("submissions"):
        if submission["case_id"] not in case_ids:
            continue
        if submission["privacy_class"] != "SENSITIVE":
            continue
        if submission["review_status"] != "ACCEPTED":
            continue
        db.set_fields(submission, privacy_status="PURGED")

    derive.refresh_all()
    db.mark_dirty(program)
    return response.obj_out(serialize.program, program)
