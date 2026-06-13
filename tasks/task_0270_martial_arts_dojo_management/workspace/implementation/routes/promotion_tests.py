"""Promotion tests: schedule, grade, signoff, cancel (PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_VALIDATION,
    ERR_WAIVER_NOT_SIGNED, ERR_MEMBER_NOT_ACTIVE, ERR_RANK_TERMINAL,
    ERR_TEST_BALANCE_TOO_HIGH, ERR_NOT_ELIGIBLE_FOR_TEST, ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, require_int, parse_pagination, paginate,
    sort_by_created, parse_iso8601,
)
from services.serialize import view, view_list
from services import domain

bp = Blueprint("promotion_tests", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]
TEST_BALANCE_CEILING_CENTS = domain.TEST_BALANCE_CEILING_CENTS
PASS_SCORE = domain.PASS_SCORE


@bp.post("/dojo/promotion-tests")
def schedule_test():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_INSTRUCTOR])
    body = get_json_body()
    require_fields(body, ["enrollment_id", "examiner_instructor_id", "scheduled_for"])

    # FK existence (priority 4)
    enrollment = db.enrollments.get(body["enrollment_id"])
    if enrollment is None:
        raise err(ERR_FK_NOT_FOUND, "enrollment_id references a non-existent enrollment.")
    examiner = db.instructors.get(body["examiner_instructor_id"])
    if examiner is None:
        raise err(ERR_FK_NOT_FOUND, "examiner_instructor_id references a non-existent instructor.")

    # structural validity (priority 5): scheduled_for well-formed
    parse_iso8601(body["scheduled_for"])

    member = db.members[enrollment["member_id"]]
    program = db.programs[enrollment["program_id"]]
    rank = domain._belt_rank(enrollment["program_id"], enrollment["current_rank_code"])

    # Gates in PRD §3.5 order: waiver, member-active, rank-terminal, balance, eligibility
    if not member["waiver_signed"]:
        raise err(ERR_WAIVER_NOT_SIGNED, "Member waiver not signed.")
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE.")
    # enrollment ACTIVE and current belt non-terminal
    if enrollment["status"] != "ACTIVE" or rank is None or rank["next_rank_code"] is None:
        raise err(ERR_RANK_TERMINAL, "Enrollment not ACTIVE or current rank is terminal.")
    if member["outstanding_balance_cents"] > TEST_BALANCE_CEILING_CENTS:
        raise err(ERR_TEST_BALANCE_TOO_HIGH, "Member outstanding balance exceeds the test ceiling.")
    # attendance + days eligibility
    now = db.now()
    days_in_rank = domain.whole_days_between(enrollment["rank_acquired_at"], now)
    if not (enrollment["rank_attendance_count"] >= program["min_attendance_for_test"]
            and days_in_rank >= program["min_days_in_rank"]):
        raise err(ERR_NOT_ELIGIBLE_FOR_TEST, "Enrollment not eligible: insufficient attendance or days in rank.")

    target_rank_code = rank["next_rank_code"]
    now_iso = db.now_iso()
    tid = db.new_id()
    test = {
        "id": tid,
        "enrollment_id": body["enrollment_id"],
        "examiner_instructor_id": body["examiner_instructor_id"],
        "target_rank_code": target_rank_code,
        "scheduled_for": body["scheduled_for"],
        "status": "SCHEDULED",
        "score": None,
        "chief_signoff_instructor_id": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.promotion_tests[tid] = test
    # generate TEST_FEE invoice and recompute balance
    domain.make_invoice(member["id"], "TEST_FEE", program["test_fee_cents"], contract_id=None)
    domain.recompute_member_balance(member["id"])
    return success(view(test), 201)


@bp.get("/dojo/promotion-tests/<tid>")
def get_test(tid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    test = db.promotion_tests.get(tid)
    if test is None:
        raise err(ERR_NOT_FOUND, "Promotion test not found.")
    return success(view(test), 200)


@bp.get("/dojo/promotion-tests")
def list_tests():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    examiner_instructor_id = request.args.get("examiner_instructor_id")
    chief_signoff_instructor_id = request.args.get("chief_signoff_instructor_id")
    status = request.args.get("status")
    items = []
    for t in db.promotion_tests.values():
        if enrollment_id is not None and t["enrollment_id"] != enrollment_id:
            continue
        if examiner_instructor_id is not None and t["examiner_instructor_id"] != examiner_instructor_id:
            continue
        if chief_signoff_instructor_id is not None and t.get("chief_signoff_instructor_id") != chief_signoff_instructor_id:
            continue
        if status is not None and t["status"] != status:
            continue
        items.append(t)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/promotion-tests/<tid>/grade")
def grade_test(tid):
    _, role = get_identity()
    require_roles(role, [ROLE_INSTRUCTOR, ROLE_CHIEF])
    test = db.promotion_tests.get(tid)
    if test is None:
        raise err(ERR_NOT_FOUND, "Promotion test not found.")
    body = get_json_body()
    require_fields(body, ["score"])
    score = body["score"]
    # structural validity (priority 14, ERR_VALIDATION): score 0..100
    require_int(score, "score", minimum=0, maximum=100, error_spec=ERR_VALIDATION)

    if test["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Promotion test not in SCHEDULED state.")

    enrollment = db.enrollments.get(test["enrollment_id"])
    target_rank = domain._belt_rank(enrollment["program_id"], test["target_rank_code"])
    requires_signoff = bool(target_rank and target_rank.get("requires_chief_signoff"))

    if score >= PASS_SCORE:
        if requires_signoff:
            test["status"] = "PASSED_PENDING_SIGNOFF"
            test["score"] = score
            domain.touch(test)
        else:
            test["status"] = "PASSED"
            test["score"] = score
            domain.touch(test)
            _apply_promotion(test, enrollment)
    else:
        test["status"] = "FAILED"
        test["score"] = score
        domain.touch(test)
    return success(view(test), 200)


@bp.post("/dojo/promotion-tests/<tid>/signoff")
def signoff_test(tid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_CHIEF])
    test = db.promotion_tests.get(tid)
    if test is None:
        raise err(ERR_NOT_FOUND, "Promotion test not found.")
    if test["status"] != "PASSED_PENDING_SIGNOFF":
        raise err(ERR_INVALID_STATE, "Promotion test not in PASSED_PENDING_SIGNOFF state.")
    # acting instructor must be a CHIEF_INSTRUCTOR
    acting = db.instructors.get(user_id)
    if acting is None or acting["rank_level"] != "CHIEF_INSTRUCTOR":
        raise err(ERR_UNAUTHORIZED, "Signoff requires a CHIEF_INSTRUCTOR.")
    test["status"] = "PASSED"
    test["chief_signoff_instructor_id"] = user_id
    domain.touch(test)
    enrollment = db.enrollments.get(test["enrollment_id"])
    _apply_promotion(test, enrollment)
    return success(view(test), 200)


@bp.post("/dojo/promotion-tests/<tid>/cancel")
def cancel_test(tid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_INSTRUCTOR])
    test = db.promotion_tests.get(tid)
    if test is None:
        raise err(ERR_NOT_FOUND, "Promotion test not found.")
    if test["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Promotion test not in SCHEDULED state.")
    test["status"] = "CANCELLED"
    domain.touch(test)
    # void the TEST_FEE invoice generated at scheduling and recompute balance
    enrollment = db.enrollments.get(test["enrollment_id"])
    member_id = enrollment["member_id"]
    # void the most recent non-void TEST_FEE invoice for this member
    candidates = [inv for inv in db.invoices.values()
                  if inv["member_id"] == member_id and inv["kind"] == "TEST_FEE"
                  and inv["status"] != "VOID"]
    candidates.sort(key=lambda i: (i["created_at"], i["id"]))
    if candidates:
        target = candidates[-1]
        target["status"] = "VOID"
        domain.touch(target)
    domain.recompute_member_balance(member_id)
    return success(view(test), 200)


def _apply_promotion(test, enrollment):
    """Apply only when enrollment ACTIVE and target == current next_rank_code."""
    if enrollment is None or enrollment["status"] != "ACTIVE":
        return
    current_rank = domain._belt_rank(enrollment["program_id"], enrollment["current_rank_code"])
    if current_rank is None or current_rank["next_rank_code"] != test["target_rank_code"]:
        return
    domain.apply_promotion(enrollment, test["target_rank_code"])
