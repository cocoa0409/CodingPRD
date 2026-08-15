"""Routes: students and student accounts."""
from flask import Blueprint, jsonify, request

from core import (
    db, auth, body, req_field, req_int, envelope_obj, paginate,
    clock_now, fmt_ts, new_entity, touch, ApiError, err_invalid_request,
    err_invalid_state, get_or_404, observe_account, recompute_account,
    spawn_refund, proration_refund_cents, bump_dirty_departments,
)
from serializers import ser_student, ser_account

bp = Blueprint("students", __name__)
BK = ("Bookkeeper",)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@bp.post("/students")
def create_student():
    auth(BK)
    data = body()
    external_ref = req_field(data, "external_ref")
    full_name = req_field(data, "full_name")
    grade_level = req_int(data, "grade_level")
    family_id = req_field(data, "family_id")
    if not isinstance(external_ref, str) or not isinstance(full_name, str) \
            or not isinstance(family_id, str):
        raise err_invalid_request(
            "external_ref, full_name and family_id must be strings.")
    if not (9 <= grade_level <= 12):
        raise err_invalid_request("grade_level must be between 9 and 12.")
    for s in db.students.values():
        if s["external_ref"] == external_ref:
            raise err_invalid_request("external_ref must be globally unique.")
    student = new_entity("students", {
        "external_ref": external_ref, "full_name": full_name,
        "grade_level": grade_level, "family_id": family_id,
        "status": "ENROLLED",
    })
    return ok(envelope_obj(ser_student(student)), 201)


@bp.get("/students")
def list_students():
    auth(ANY)
    rows = list(db.students.values())
    if "family_id" in request.args:
        rows = [s for s in rows if s["family_id"] == request.args["family_id"]]
    return ok(paginate(rows, ser_student))


@bp.get("/students/<id>")
def get_student(id):
    auth(ANY)
    return ok(envelope_obj(ser_student(get_or_404("students", id, "student"))))


@bp.get("/students/<id>/student-accounts")
def list_student_accounts(id):
    auth(ANY)
    get_or_404("students", id, "student")
    rows = [a for a in db.accounts.values() if a["student_id"] == id]
    for a in rows:
        observe_account(a)
    return ok(paginate(rows, ser_account))


@bp.post("/students/<id>/withdraw")
def withdraw_student(id):
    auth(BK)
    student = get_or_404("students", id, "student")
    if student["status"] != "ENROLLED":
        raise err_invalid_state("Only an ENROLLED student can be withdrawn.")
    accounts = [a for a in db.accounts.values() if a["student_id"] == id]
    accounts.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in accounts:
        observe_account(a)
    for a in accounts:
        if a["posture"] == "COLLECTIONS":
            raise ApiError("ERR_STUDENT_IN_COLLECTIONS", 409,
                           "An account of the student is in COLLECTIONS.")

    # depth-3 cascade: ACTIVE enrollments -> WITHDRAWN with proration refunds
    for account in accounts:
        year = db.years.get(account["school_year_id"])
        enrollments = [e for e in db.enrollments.values()
                       if e["student_account_id"] == account["id"]
                       and e["status"] == "ACTIVE"]
        enrollments.sort(key=lambda e: (e["created_at"], e["_seq"]))
        for e in enrollments:
            e["status"] = "WITHDRAWN"
            e["withdrawn_at"] = fmt_ts(clock_now())
            touch(e)
            offering = db.offerings.get(e["offering_id"])
            assessment = next(
                (a for a in db.assessments.values()
                 if a.get("enrollment_id") == e["id"]), None)
            if offering is None or assessment is None or year is None:
                continue
            item = db.fee_items.get(assessment["fee_item_id"])
            if item is not None and not item.get("refundable", True):
                continue  # withdrawal spawns a refund only when refundable
            cents = proration_refund_cents(year, offering, assessment)
            spawn_refund(account, "WITHDRAWAL", cents,
                         fee_assessment_id=assessment["id"])

        # COMPLETED purchases of refundable items -> full-amount refunds
        purchases = [p for p in db.purchases.values()
                     if p["student_account_id"] == account["id"]
                     and p["status"] == "COMPLETED"]
        purchases.sort(key=lambda p: (p["created_at"], p["_seq"]))
        for p in purchases:
            item = db.purchase_items.get(p["item_id"])
            if item is not None and item.get("refundable", True):
                spawn_refund(account, "WITHDRAWAL", p["amount_cents"],
                             purchase_id=p["id"])

        # ACTIVE plans -> CANCELLED; unpaid installments waived
        plans = [pl for pl in db.plans.values()
                 if pl["student_account_id"] == account["id"]
                 and pl["status"] == "ACTIVE"]
        plans.sort(key=lambda pl: (pl["created_at"], pl["_seq"]))
        for pl in plans:
            _cancel_plan(pl)

    for account in accounts:
        recompute_account(account)
    bump_dirty_departments()
    student["status"] = "WITHDRAWN"
    touch(student)
    return ok(envelope_obj(ser_student(student)))


def _cancel_plan(plan):
    """Shared cancel cascade: waive unpaid installments, return covered
    assessments to the normal waterfall (ASSESSED / PARTIALLY_PAID)."""
    plan["status"] = "CANCELLED"
    touch(plan)
    for i in db.installments.values():
        if i["payment_plan_id"] == plan["id"] and \
                i["status"] in ("SCHEDULED", "DUE", "PAST_DUE"):
            i["status"] = "WAIVED_BY_DEFAULT"
            touch(i)
    for aid, _w in plan["_covered"]:
        a = db.assessments.get(aid)
        if a is not None and a["status"] == "PAYMENT_PLAN":
            a["status"] = "PARTIALLY_PAID" if a["allocated_cents"] > 0 \
                else "ASSESSED"
            touch(a)


@bp.post("/students/<id>/graduate")
def graduate_student(id):
    auth(BK)
    student = get_or_404("students", id, "student")
    if student["status"] != "ENROLLED":
        raise err_invalid_state("Only an ENROLLED student can be graduated.")
    if student["grade_level"] != 12:
        raise ApiError("ERR_NOT_GRADUATION_CANDIDATE", 422,
                       "Only grade-12 students are graduation candidates.")
    accounts = [a for a in db.accounts.values() if a["student_id"] == id]
    for a in accounts:
        observe_account(a)
    for a in accounts:
        if a["posture"] in ("GRADUATION_HOLD", "COLLECTIONS"):
            raise ApiError(
                "ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION", 409,
                "An account of the student holds a blocking posture.")
    student["status"] = "GRADUATED"
    touch(student)
    return ok(envelope_obj(ser_student(student)))


# ---------------------------------------------------------------------------
# Student accounts
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/student-accounts")
def create_account(id):
    auth(BK)
    get_or_404("years", id, "school year")
    data = body()
    student_id = req_field(data, "student_id")
    student = db.students.get(student_id)
    if student is None:
        from core import err_ref_not_found
        raise err_ref_not_found("student")
    account = new_entity("accounts", {
        "school_year_id": id,
        "student_id": student_id,
        "assessed_cents": 0,
        "waived_cents": 0,
        "paid_cents": 0,
        "balance_cents": 0,
        "posture": "CLEAR",
        "last_posture_check_at": fmt_ts(clock_now()),
    })
    return ok(envelope_obj(ser_account(account)), 201)


@bp.get("/school-years/<id>/student-accounts")
def list_accounts(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [a for a in db.accounts.values() if a["school_year_id"] == id]
    for a in rows:
        observe_account(a)
    if "student_id" in request.args:
        rows = [a for a in rows if a["student_id"] == request.args["student_id"]]
    if "posture" in request.args:
        rows = [a for a in rows if a["posture"] == request.args["posture"]]
    return ok(paginate(rows, ser_account))


@bp.get("/student-accounts/<id>")
def get_account(id):
    auth(ANY)
    account = get_or_404("accounts", id, "student account")
    observe_account(account)
    return ok(envelope_obj(ser_account(account)))


@bp.get("/student-accounts/<id>/summary")
def account_summary(id):
    auth(ANY)
    account = get_or_404("accounts", id, "student account")
    observe_account(account)
    open_cases = sum(
        1 for c in db.cases.values()
        if c["student_account_id"] == id and c["status"] in ("OPEN", "PAYMENT_PROMISED"))
    from core import family_balance
    return ok(envelope_obj({
        "balance_cents": account["balance_cents"],
        "family_balance_cents": family_balance(account),
        "posture": account["posture"],
        "assessed_cents": account["assessed_cents"],
        "waived_cents": account["waived_cents"],
        "paid_cents": account["paid_cents"],
        "open_case_count": open_cases,
    }))
