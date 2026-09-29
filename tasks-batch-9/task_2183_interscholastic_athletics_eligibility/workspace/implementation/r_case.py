"""Eligibility cases: intake, documents, ladder, appeal, activation, fee axis."""
from flask import Blueprint, request

from core import (
    DB, ALL_ROLES, DOC_TYPES, auth, own, body, ok, ok_list, fail, req_str,
    req_enum, req_int, req_date, opt_str, new_record, touch, now, now_date,
    pagination, paginate, by_created, get_student, get_season, get_case,
    ser_case, ser_document,
)
import calc
import domain

bp = Blueprint("cases", __name__)

CASE_STATUSES = ["INTAKE", "UNDER_REVIEW", "UNDER_APPEAL", "PROVISIONAL_ELIGIBLE",
                 "ELIGIBLE", "MEDICALLY_SUSPENDED", "INELIGIBLE"]


def _case_school(case):
    student = DB.students.get(case["student_id"])
    return DB.schools.get(student["school_id"]) if student else None


@bp.post("/athletics/eligibility-cases")
def create_case():
    p = auth(["SchoolAthleticDirector"])
    b = body()
    raw_student = b.get("student_id")
    raw_season = b.get("sport_season_id")
    student = None
    if isinstance(raw_student, str):
        student = get_student(raw_student)
        own(p, student["school_id"])
    if isinstance(raw_season, str):
        get_season(raw_season)
    student_id = req_str(b, "student_id")
    sport_season_id = req_str(b, "sport_season_id")
    student = DB.students[student_id]
    season = DB.seasons[sport_season_id]

    for c in DB.cases.values():
        if c["student_id"] == student_id and c["sport_season_id"] == sport_season_id:
            fail("ERR_DUPLICATE_ELIGIBILITY_CASE",
                 "an eligibility case already exists for this athlete and season")

    school = DB.schools.get(student["school_id"])
    fee_amount = calc.participation_fee_assessment(student, season, school) if school else 0
    rec = new_record({
        "student_id": student_id,
        "sport_season_id": sport_season_id,
        "status": "INTAKE",
        "fee_status": "PAID" if fee_amount == 0 else "ASSESSED",
        "ineligibility_reason": None,
        "gpa_variant_applied": None,
        "effective_gpa": None,
        "fee_amount_cents": fee_amount,
        "fee_paid_cents": 0,
        "fee_waived_cents": 0,
        "fee_refunded_cents": 0,
        "fee_outstanding_cents": fee_amount,
        "appeal_count": 0,
        "evaluation_count": 0,
        "provisional_revoked_at": None,
        "activated_at": None,
    })
    DB.cases[rec["id"]] = rec
    return ok(ser_case(rec), 201)


@bp.post("/athletics/eligibility-cases/<cid>/clearance-documents")
def create_document(cid):
    p = auth(["SchoolAthleticDirector", "MedicalOfficer"])
    case = get_case(cid)
    school = _case_school(case)
    own(p, school["id"] if school else None)
    b = body()
    doc_type = req_enum(b, "doc_type", DOC_TYPES)
    issued_on = req_date(b, "issued_on")
    expires_on = req_date(b, "expires_on")
    signer_name = req_str(b, "signer_name")
    rec = new_record({
        "eligibility_case_id": case["id"],
        "doc_type": doc_type,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "signer_name": signer_name,
    }, versioned=False)
    DB.documents[rec["id"]] = rec
    return ok(ser_document(rec), 201)


@bp.post("/athletics/eligibility-cases/<cid>/evaluate")
def evaluate_case(cid):
    p = auth(["EligibilityReviewer"])
    case = get_case(cid)
    if case["status"] not in ("INTAKE", "UNDER_REVIEW", "UNDER_APPEAL"):
        fail("ERR_INVALID_STATE", "a case in %s admits no evaluation" % case["status"])
    season = DB.seasons.get(case["sport_season_id"])
    if season is None or season["status"] not in ("PRACTICE_OPEN", "REGULAR_SEASON"):
        fail("ERR_SEASON_NOT_OPEN", "the governing season does not admit evaluation")
    student = DB.students.get(case["student_id"])
    if student is not None and student["academic_record_submitted_by"] == p.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the principal who posted the academic record may not rule on this case")
    if student is None or student["academic_record_submitted_at"] is None:
        fail("ERR_ACADEMIC_RECORD_MISSING", "no academic record has been posted")

    variant, effective = calc.academic_gpa_evaluation(student, season)
    reason = calc.eligibility_ladder_evaluation(case, student, season, effective)
    case["gpa_variant_applied"] = variant
    case["effective_gpa"] = effective
    case["ineligibility_reason"] = reason
    case["status"] = "INELIGIBLE" if reason else "PROVISIONAL_ELIGIBLE"
    case["evaluation_count"] += 1
    touch(case)
    return ok(ser_case(case))


@bp.post("/athletics/eligibility-cases/<cid>/appeal")
def appeal_case(cid):
    p = auth(["SchoolAthleticDirector"])
    case = get_case(cid)
    school = _case_school(case)
    own(p, school["id"] if school else None)
    b = body()
    opt_str(b, "appeal_note", None)
    if case["status"] != "INELIGIBLE":
        fail("ERR_INVALID_STATE", "only an INELIGIBLE case may be appealed")
    if case["appeal_count"] >= calc.MAX_APPEALS:
        fail("ERR_APPEAL_LIMIT_REACHED", "this case has already appealed twice")
    case["status"] = "UNDER_APPEAL"
    case["appeal_count"] += 1
    touch(case)
    return ok(ser_case(case))


@bp.post("/athletics/eligibility-cases/<cid>/activate")
def activate_case(cid):
    auth(["EligibilityReviewer"])
    case = get_case(cid)
    if case["status"] != "PROVISIONAL_ELIGIBLE":
        fail("ERR_CASE_NOT_ACTIVATABLE",
             "only a PROVISIONAL_ELIGIBLE case may be activated")
    school = _case_school(case)
    if school is not None and school["sanction_status"] == "SUSPENDED":
        fail("ERR_SCHOOL_SANCTIONED", "the athlete's school is SUSPENDED")
    season = DB.seasons.get(case["sport_season_id"])
    today = now_date()
    credentialed = False
    if school is not None and season is not None:
        for c in DB.credentials.values():
            if c["school_id"] == school["id"] and c["sport"] == season["sport"] \
                    and c["role_title"] == "HEAD_COACH" and c["status"] == "CLEARED" \
                    and c["certification_expires_on"] > today:
                credentialed = True
                break
    if not credentialed:
        fail("ERR_COACH_NOT_CREDENTIALED",
             "the school holds no cleared, unexpired head-coach credential for this sport")
    if domain.student_has_live_injury(case["student_id"]):
        fail("ERR_ATHLETE_MEDICALLY_SUSPENDED", "the athlete is under a live medical hold")
    if case["fee_outstanding_cents"] != 0:
        fail("ERR_FEE_OUTSTANDING", "the participation fee is not settled")
    case["status"] = "ELIGIBLE"
    case["activated_at"] = now()
    touch(case)
    return ok(ser_case(case))


# ---------------------------------------------------------------------------
# Fee axis
# ---------------------------------------------------------------------------
@bp.post("/athletics/eligibility-cases/<cid>/fee-payments")
def fee_payment(cid):
    p = auth(["SchoolAthleticDirector"])
    case = get_case(cid)
    school = _case_school(case)
    own(p, school["id"] if school else None)
    b = body()
    amount = req_int(b, "amount_cents")
    if case["fee_status"] not in ("ASSESSED", "PARTIALLY_PAID", "WAIVER_DENIED"):
        fail("ERR_INVALID_STATE",
             "a case whose fee_status is %s admits no payment" % case["fee_status"])
    if not (0 < amount <= case["fee_outstanding_cents"]):
        fail("ERR_FEE_OVERPAYMENT",
             "amount_cents must be strictly above 0 and no greater than the outstanding balance")
    case["fee_paid_cents"] += amount
    domain.recompute_outstanding(case)
    case["fee_status"] = "PAID" if case["fee_outstanding_cents"] == 0 else "PARTIALLY_PAID"
    touch(case)
    if school is not None:
        school["fee_collected_cents"] += amount
        touch(school)
    return ok(ser_case(case))


@bp.post("/athletics/eligibility-cases/<cid>/fee-waiver-requests")
def fee_waiver_request(cid):
    p = auth(["SchoolAthleticDirector"])
    case = get_case(cid)
    school = _case_school(case)
    own(p, school["id"] if school else None)
    b = body()
    req_str(b, "waiver_reason")
    if case["fee_status"] not in ("ASSESSED", "PARTIALLY_PAID") \
            or case["fee_outstanding_cents"] <= 0:
        fail("ERR_INVALID_STATE",
             "a case whose fee_status is %s admits no waiver request" % case["fee_status"])
    case["fee_status"] = "WAIVER_REQUESTED"
    touch(case)
    return ok(ser_case(case))


@bp.post("/athletics/eligibility-cases/<cid>/fee-waiver-decisions")
def fee_waiver_decision(cid):
    auth(["AssociationAdmin"])
    case = get_case(cid)
    b = body()
    decision = req_enum(b, "decision", ["APPROVE", "DENY"])
    opt_str(b, "decision_note", None)
    if case["fee_status"] != "WAIVER_REQUESTED":
        fail("ERR_INVALID_STATE", "no waiver request is pending on this case")
    if decision == "APPROVE":
        case["fee_waived_cents"] = case["fee_outstanding_cents"]
        domain.recompute_outstanding(case)
        case["fee_status"] = "WAIVED"
    else:
        case["fee_status"] = "WAIVER_DENIED"
    touch(case)
    return ok(ser_case(case))


@bp.post("/athletics/eligibility-cases/<cid>/fee-refunds")
def fee_refund(cid):
    auth(["AssociationAdmin"])
    case = get_case(cid)
    b = body()
    req_str(b, "refund_reason")
    if case["fee_status"] != "PAID":
        fail("ERR_INVALID_STATE", "a refund is declared only from PAID")
    refundable = case["fee_paid_cents"] - case["fee_refunded_cents"]
    if refundable <= 0:
        fail("ERR_NOTHING_TO_REFUND", "nothing has been collected on this case")
    case["fee_refunded_cents"] = case["fee_paid_cents"]
    domain.recompute_outstanding(case)
    case["fee_status"] = "REFUNDED"
    touch(case)
    school = _case_school(case)
    if school is not None:
        school["fee_collected_cents"] -= refundable
        touch(school)
    return ok(ser_case(case))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/athletics/eligibility-cases/<cid>")
def read_case(cid):
    auth(ALL_ROLES)
    return ok(ser_case(get_case(cid)))


@bp.get("/athletics/eligibility-cases")
def list_cases():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.cases.values())
    sid = request.args.get("student_id")
    if sid is not None:
        rows = [c for c in rows if c["student_id"] == sid]
    season_id = request.args.get("sport_season_id")
    if season_id is not None:
        rows = [c for c in rows if c["sport_season_id"] == season_id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_case(c) for c in page], limit, offset, total)


@bp.get("/athletics/eligibility-cases/<cid>/clearance-documents")
def list_documents(cid):
    auth(ALL_ROLES)
    case = get_case(cid)
    limit, offset = pagination()
    rows = [d for d in DB.documents.values() if d["eligibility_case_id"] == case["id"]]
    doc_type = request.args.get("doc_type")
    if doc_type is not None:
        rows = [d for d in rows if d["doc_type"] == doc_type]
    rows = by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_document(d) for d in page], limit, offset, total)
