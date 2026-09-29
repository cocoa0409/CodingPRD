"""Appeals and the compensating cascade of a granted appeal (section 3.8)."""

from flask import Blueprint

import auth
import calc
import clock
import constants as K
import db
import derive
import emit
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("appeals", __name__)

READ_ROLES = ("ProgramAdmin", "AppealReviewer", "VerificationAnalyst")
OPEN_APPEAL_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REMANDED")


def _appeal_or_404(appeal_id):
    appeal = db.get("appeals", appeal_id)
    if appeal is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND")
    return appeal


def _dependent_notices(dependent_id):
    return db.ordered("notices", lambda n: n["dependent_id"] == dependent_id)


@bp.route("/appeals", methods=["POST"])
@endpoint("Employee")
def file_appeal():
    raw = validate.body()
    auth.soft_owner_check_case(raw.get("case_id"))
    auth.soft_owner_check_dependent(raw.get("dependent_id"))

    case_id = validate.req_id(raw, "case_id")
    dependent_id = validate.req_id(raw, "dependent_id")
    grounds = validate.req_enum(raw, "grounds", K.APPEAL_GROUNDS)
    statement = validate.req_str(raw, "statement")
    affidavit_reference = validate.opt_str(raw, "affidavit_reference")
    custody_order_reference = validate.opt_str(raw, "custody_order_reference")

    case = db.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    dependent = db.get("dependents", dependent_id)
    if dependent is None:
        raise ApiError("ERR_DEPENDENT_NOT_FOUND")

    if case["status"] not in ("ESCALATED", "NON_RESPONSIVE"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if dependent["coverage_status"] not in ("TERMINATION_PENDING", "TERMINATED"):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    for existing in db.collection("appeals").values():
        if (
            existing["dependent_id"] == dependent["id"]
            and existing["status"] in OPEN_APPEAL_STATUSES
        ):
            raise ApiError("ERR_APPEAL_STATE_INVALID")

    now = clock.now()
    live = [n for n in _dependent_notices(dependent["id"]) if n["status"] != "RESCINDED"]
    live.sort(key=lambda n: (n["issued_at"], n["_seq"]))
    if not live:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    latest = live[-1]
    if now > clock.add_days_dt(latest["issued_at"], K.APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    if grounds == "DOMESTIC_PARTNERSHIP_AFFIDAVIT":
        rule = calc.find_rule(
            case["program_id"], dependent["relationship_type"], "AUDIT"
        )
        if affidavit_reference is None or rule is None or not rule.get(
            "affidavit_allowed"
        ):
            raise ApiError("ERR_APPEAL_GROUNDS_UNSUPPORTED")
    elif grounds == "CUSTODY_ARRANGEMENT":
        if custody_order_reference is None or dependent[
            "relationship_type"
        ] not in K.CUSTODY_RELATIONSHIP_TYPES:
            raise ApiError("ERR_APPEAL_GROUNDS_UNSUPPORTED")

    appeal = db.insert(
        "appeals",
        {
            "case_id": case["id"],
            "dependent_id": dependent["id"],
            "grounds": grounds,
            "statement": statement,
            "affidavit_reference": affidavit_reference,
            "custody_order_reference": custody_order_reference,
            "status": "SUBMITTED",
            "round_number": 1,
            "reviewer_user_id": None,
            "assigned_at": None,
            "decided_at": None,
            "decision_rationale": None,
            "remand_reason": None,
        },
    )
    derive.refresh_all()
    return response.obj_out(serialize.appeal, appeal, 201)


@bp.route("/appeals/<appeal_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    return response.obj_out(serialize.appeal, appeal)


@bp.route("/appeals", methods=["GET"])
@endpoint(*READ_ROLES)
def list_appeals():
    case_id = validate.query_filter("case_id")
    dependent_id = validate.query_filter("dependent_id")
    status = validate.query_filter("status")
    rows = db.ordered(
        "appeals",
        lambda a: (case_id is None or a["case_id"] == case_id)
        and (dependent_id is None or a["dependent_id"] == dependent_id)
        and (status is None or a["status"] == status),
    )
    return response.arr_out(serialize.appeal, rows, validate.paginate(rows))


@bp.route("/appeals/<appeal_id>/assign", methods=["POST"])
@endpoint("AppealReviewer")
def assign_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    actor = auth.acting_user()

    for submission in db.collection("submissions").values():
        if submission["dependent_id"] != appeal["dependent_id"]:
            continue
        if submission.get("reviewed_by_user_id") == actor:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    db.set_fields(
        appeal,
        status="UNDER_REVIEW",
        reviewer_user_id=actor,
        assigned_at=clock.now(),
    )
    derive.refresh_all()
    return response.obj_out(serialize.appeal, appeal)


def _grant_cascade(appeal, dependent, case, now):
    # 1. restore the dependent
    if dependent["coverage_status"] == "TERMINATION_PENDING":
        db.set_fields(
            dependent, coverage_status="VERIFIED", documentation_complete=True
        )
    elif dependent["coverage_status"] == "TERMINATED":
        db.set_fields(
            dependent,
            coverage_status="REINSTATED",
            reinstated_at=now,
            coverage_end_date=None,
        )

    # 2. rescind every live notice of that dependent
    for notice in _dependent_notices(dependent["id"]):
        if notice["status"] in ("ISSUED", "FINAL"):
            db.set_fields(
                notice,
                status="RESCINDED",
                rescinded_at=now,
                rescission_reason="APPEAL_GRANTED",
            )

    # 3. one rescission communication on the case
    emit.communication(case, "RESCISSION_NOTICE")

    # 4. void every live recovery, refunding what was collected
    for recovery in db.ordered(
        "recoveries", lambda r: r["dependent_id"] == dependent["id"]
    ):
        if recovery["status"] in ("OPEN", "DEMAND_ISSUED", "PARTIALLY_RECOVERED"):
            db.set_fields(
                recovery,
                status="VOIDED",
                refund_due_cents=recovery["recovered_cents"],
            )

    # 5. the case re-opens, or completes when nothing is left unresolved
    if case is not None and case["status"] == "ESCALATED":
        unresolved = False
        for dep_id in case.get("in_scope_dependent_ids") or []:
            other = db.get("dependents", dep_id)
            if other is not None and other["coverage_status"] in K.UNRESOLVED_COVERAGE_STATUSES:
                unresolved = True
                break
        if unresolved:
            db.set_fields(case, status="IN_PROGRESS")
        else:
            db.set_fields(case, status="COMPLETE", completed_at=now)


@bp.route("/appeals/<appeal_id>/decision", methods=["POST"])
@endpoint("AppealReviewer")
def decide_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", K.APPEAL_DECISIONS)
    decision_rationale = validate.opt_str(payload, "decision_rationale")
    remand_reason = validate.opt_str(payload, "remand_reason")

    if appeal.get("reviewer_user_id") != auth.acting_user():
        raise ApiError("ERR_APPEAL_REVIEWER_MISMATCH")
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    if decision == "REMAND" and appeal["round_number"] >= K.MAX_APPEAL_ROUNDS:
        raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")

    now = clock.now()
    dependent = db.get("dependents", appeal["dependent_id"])
    case = db.get("cases", appeal["case_id"])

    db.set_fields(appeal, decided_at=now)
    if decision_rationale is not None:
        db.set_fields(appeal, decision_rationale=decision_rationale)

    if decision == "GRANT":
        db.set_fields(appeal, status="GRANTED")
        _grant_cascade(appeal, dependent, case, now)
    elif decision == "DENY":
        db.set_fields(appeal, status="DENIED")
        if case is not None:
            derive.recompute_case(case)
            derive.maybe_complete_case(case)
    else:
        db.set_fields(appeal, status="REMANDED", remand_reason=remand_reason)

    derive.refresh_all()
    return response.obj_out(serialize.appeal, appeal)


@bp.route("/appeals/<appeal_id>/resubmit", methods=["POST"])
@endpoint("Employee")
def resubmit_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    dependent = db.get("dependents", appeal["dependent_id"])
    auth.require_owns_dependent(dependent)

    payload = validate.body()
    statement = validate.req_str(payload, "statement")
    affidavit_reference = validate.opt_str(payload, "affidavit_reference")
    custody_order_reference = validate.opt_str(payload, "custody_order_reference")

    if appeal["status"] != "REMANDED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    if appeal["round_number"] >= K.MAX_APPEAL_ROUNDS:
        raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")

    db.set_fields(
        appeal,
        status="SUBMITTED",
        round_number=appeal["round_number"] + 1,
        statement=statement,
        remand_reason=None,
        reviewer_user_id=None,
        assigned_at=None,
    )
    if affidavit_reference is not None:
        db.set_fields(appeal, affidavit_reference=affidavit_reference)
    if custody_order_reference is not None:
        db.set_fields(appeal, custody_order_reference=custody_order_reference)

    derive.refresh_all()
    return response.obj_out(serialize.appeal, appeal)
