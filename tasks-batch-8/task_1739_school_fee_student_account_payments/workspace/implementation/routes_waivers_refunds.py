"""Routes: waiver programs, waiver applications, refunds."""
from flask import Blueprint, jsonify, request

from core import (
    db, auth, body, req_field, req_int, envelope_obj, paginate, clock_now,
    fmt_ts, new_entity, touch, ApiError, err_invalid_request,
    err_invalid_state, err_ref_not_found, get_or_404, get_scoped,
    recompute_account, run_stacking, write_ledger, bump_dirty_departments,
)
from serializers import ser_program, ser_application, ser_refund

bp = Blueprint("waivers_refunds", __name__)
BK = ("Bookkeeper",)
FM = ("FamilyMember",)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Waiver programs
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/waiver-programs")
def create_program(id):
    auth(BK)
    get_or_404("years", id, "school year")
    data = body()
    name = req_field(data, "name")
    pct_bp = req_int(data, "waiver_pct_bp")
    priority = req_int(data, "stacking_priority")
    max_waived = req_int(data, "max_waived_per_student_cents")
    grade_min = req_int(data, "eligibility_grade_min")
    grade_max = req_int(data, "eligibility_grade_max")
    if not isinstance(name, str):
        raise err_invalid_request("name must be a string.")
    if not (1 <= pct_bp <= 10000):
        raise err_invalid_request("waiver_pct_bp must be within 1..10000.")
    if max_waived < 0:
        raise err_invalid_request(
            "max_waived_per_student_cents must be at least 0.")
    if grade_max < grade_min:
        raise err_invalid_request(
            "eligibility_grade_max must be at least eligibility_grade_min.")
    program = new_entity("programs", {
        "school_year_id": id, "name": name, "waiver_pct_bp": pct_bp,
        "stacking_priority": priority,
        "max_waived_per_student_cents": max_waived,
        "eligibility_grade_min": grade_min,
        "eligibility_grade_max": grade_max,
        "status": "ACTIVE",
    })
    return ok(envelope_obj(ser_program(program)), 201)


@bp.get("/school-years/<id>/waiver-programs")
def list_programs(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [p for p in db.programs.values() if p["school_year_id"] == id]
    if "status" in request.args:
        rows = [p for p in rows if p["status"] == request.args["status"]]
    return ok(paginate(rows, ser_program))


@bp.get("/school-years/<id>/waiver-programs/<programId>")
def get_program(id, programId):
    auth(ANY)
    get_or_404("years", id, "school year")
    p = get_scoped("programs", programId, "school_year_id", id,
                   "waiver program")
    return ok(envelope_obj(ser_program(p)))


@bp.post("/school-years/<id>/waiver-programs/<programId>/suspend")
def suspend_program(id, programId):
    auth(BK)
    get_or_404("years", id, "school year")
    p = get_scoped("programs", programId, "school_year_id", id,
                   "waiver program")
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE program can be suspended.")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok(envelope_obj(ser_program(p)))


# ---------------------------------------------------------------------------
# Waiver applications
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/waiver-applications")
def submit_application(id):
    uid, _role = auth(FM)
    account = get_or_404("accounts", id, "student account")
    data = body()
    program = None
    if "waiver_program_id" in data and data["waiver_program_id"] is not None:
        program = db.programs.get(data["waiver_program_id"])
        if program is None or program["school_year_id"] != account["school_year_id"]:
            raise err_ref_not_found("waiver program")
    req_field(data, "waiver_program_id")
    app = new_entity("applications", {
        "student_account_id": id,
        "waiver_program_id": program["id"],
        "submitted_by_user_id": uid,
        "reviewed_by_user_id": None,
        "status": "PENDING",
    })
    return ok(envelope_obj(ser_application(app)), 201)


@bp.get("/student-accounts/<id>/waiver-applications")
def list_applications(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [a for a in db.applications.values() if a["student_account_id"] == id]
    if "status" in request.args:
        rows = [a for a in rows if a["status"] == request.args["status"]]
    if "waiver_program_id" in request.args:
        rows = [a for a in rows
                if a["waiver_program_id"] == request.args["waiver_program_id"]]
    return ok(paginate(rows, ser_application))


@bp.get("/student-accounts/<id>/waiver-applications/<applicationId>")
def get_application(id, applicationId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    app = get_scoped("applications", applicationId, "student_account_id", id,
                     "waiver application")
    return ok(envelope_obj(ser_application(app)))


def _self_approval_guard(uid, app):
    if uid == app["submitted_by_user_id"]:
        raise ApiError("ERR_WAIVER_SELF_APPROVAL", 403,
                       "The reviewer must differ from the submitter.")


@bp.post("/student-accounts/<id>/waiver-applications/<applicationId>/approve")
def approve_application(id, applicationId):
    uid, _role = auth(BK)
    account = get_or_404("accounts", id, "student account")
    app = get_scoped("applications", applicationId, "student_account_id", id,
                     "waiver application")
    if app["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING application can be approved.")
    data = body()
    expected = req_int(data, "expected_account_version")
    program = db.programs.get(app["waiver_program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_WAIVER_PROGRAM_SUSPENDED", 409,
                       "The waiver program is not ACTIVE.")
    # rung 13 (segregation) before rung 14 (eligibility)
    _self_approval_guard(uid, app)
    student = db.students.get(account["student_id"])
    if student is None or not (program["eligibility_grade_min"]
                               <= student["grade_level"]
                               <= program["eligibility_grade_max"]):
        raise ApiError("ERR_WAIVER_INELIGIBLE", 422,
                       "The student's grade is outside the eligibility band.")
    # rung 23: OCC last
    if expected != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_account_version does not match the account's "
                       "current version.")
    app["status"] = "APPROVED"
    app["reviewed_by_user_id"] = uid
    touch(app)
    # final stacking: recompute all program contributions from scratch
    run_stacking(account)
    recompute_account(account)
    return ok(envelope_obj(ser_application(app)))


@bp.post("/student-accounts/<id>/waiver-applications/<applicationId>/deny")
def deny_application(id, applicationId):
    uid, _role = auth(BK)
    get_or_404("accounts", id, "student account")
    app = get_scoped("applications", applicationId, "student_account_id", id,
                     "waiver application")
    if app["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING application can be denied.")
    _self_approval_guard(uid, app)
    app["status"] = "DENIED"
    app["reviewed_by_user_id"] = uid
    touch(app)
    return ok(envelope_obj(ser_application(app)))


@bp.post("/student-accounts/<id>/waiver-applications/<applicationId>/revoke")
def revoke_application(id, applicationId):
    uid, _role = auth(BK)
    account = get_or_404("accounts", id, "student account")
    app = get_scoped("applications", applicationId, "student_account_id", id,
                     "waiver application")
    if app["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED application can be revoked.")
    _self_approval_guard(uid, app)
    app["status"] = "REVOKED"
    touch(app)
    # final stacking without the revoked program; WAIVED assessments that lose
    # full coverage return to ASSESSED (or PARTIALLY_PAID when payments landed)
    run_stacking(account)
    recompute_account(account)
    return ok(envelope_obj(ser_application(app)))


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/refunds")
def create_refund(id):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    recompute_account(account, bump=False)
    data = body()
    amount = req_int(data, "amount_cents")
    credit = -account["balance_cents"]
    if amount <= 0 or amount > credit:
        raise err_invalid_request(
            "amount_cents must be greater than zero and no more than the "
            "account's credit balance.")
    refund = new_entity("refunds", {
        "student_account_id": id,
        "fee_assessment_id": None,
        "purchase_id": None,
        "reason": "OVERPAYMENT_RETURN",
        "refund_cents": amount,
        "status": "PENDING",
    })
    return ok(envelope_obj(ser_refund(refund)), 201)


@bp.get("/student-accounts/<id>/refunds")
def list_refunds(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [r for r in db.refunds.values() if r["student_account_id"] == id]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if "reason" in request.args:
        rows = [r for r in rows if r["reason"] == request.args["reason"]]
    return ok(paginate(rows, ser_refund))


@bp.get("/student-accounts/<id>/refunds/<refundId>")
def get_refund(id, refundId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    r = get_scoped("refunds", refundId, "student_account_id", id, "refund")
    return ok(envelope_obj(ser_refund(r)))


@bp.post("/student-accounts/<id>/refunds/<refundId>/execute")
def execute_refund(id, refundId):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    refund = get_scoped("refunds", refundId, "student_account_id", id, "refund")
    if refund["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING refund can be executed.")
    if refund["refund_cents"] <= 0:
        raise ApiError("ERR_ZERO_REFUND", 422,
                       "A zero-valued refund cannot execute.")
    cents = refund["refund_cents"]
    if refund.get("fee_assessment_id"):
        a = db.assessments.get(refund["fee_assessment_id"])
        if a is not None:
            a["allocated_cents"] -= cents
            a["refunded_cents"] += cents
            a["status"] = "REFUNDED"  # obligation collapses to retained portion
            a["payment_plan_id"] = None
            touch(a)
            write_ledger(id, a["department_id"], "DISTRIBUTION_REVERSAL",
                         -cents, source_payment_id=None)
    elif refund.get("purchase_id"):
        p = db.purchases.get(refund["purchase_id"])
        if p is not None:
            if p["status"] == "COMPLETED":
                p["status"] = "REFUNDED"
            p["refunded_cents"] += cents
            touch(p)
            item = db.purchase_items.get(p["item_id"])
            if item is not None:
                item["sold_count"] = max(0, item["sold_count"] - 1)
                touch(item)
                write_ledger(id, item["department_id"], "DISTRIBUTION_REVERSAL",
                             -cents, source_payment_id=None)
    # OVERPAYMENT_RETURN: no linkage; paid_cents drops via recompute
    refund["status"] = "EXECUTED"
    touch(refund)
    recompute_account(account)
    bump_dirty_departments()
    return ok(envelope_obj(ser_refund(refund)))


@bp.post("/student-accounts/<id>/refunds/<refundId>/deny")
def deny_refund(id, refundId):
    auth(BK)
    get_or_404("accounts", id, "student account")
    refund = get_scoped("refunds", refundId, "student_account_id", id, "refund")
    if refund["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING refund can be denied.")
    refund["status"] = "DENIED"
    touch(refund)
    return ok(envelope_obj(ser_refund(refund)))
