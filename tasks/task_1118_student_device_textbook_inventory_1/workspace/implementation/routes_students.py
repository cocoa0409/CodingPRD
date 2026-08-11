"""StudentAccount, FamilyAgreement, InsurancePolicy endpoints."""
from flask import Blueprint, request

from core import (STORE, agreement_json, auth, base_record, body, fail,
                  family_path_scope, get_agreement, get_policy, get_program,
                  get_student, list_response, now, ok_object, opt_bool,
                  opt_int, policy_json, reject_stray_occ, req_int, req_str,
                  student_json, touch, unit_json)

bp = Blueprint("students", __name__)

STUDENT_READ = ["DistrictAdmin", "Registrar", "SiteTechnician"]
STUDENT_READ_FAMILY = ["DistrictAdmin", "Registrar", "SiteTechnician", "Family"]
AGREEMENT_READ = ["DistrictAdmin", "Registrar", "Family"]
POLICY_READ = ["DistrictAdmin", "Registrar", "Family"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ------------------------------------------------------------ students -----
@bp.post("/api/programs/<progId>/students")
def create_student(progId):
    b = body()
    ext_id = req_str(b, "student_external_id")
    full_name = req_str(b, "full_name")
    grade_level = req_int(b, "grade_level", minimum=0, maximum=12)
    free_lunch = opt_bool(b, "free_lunch_eligible", False)
    reject_stray_occ(b)
    auth(["Registrar"])
    prog = get_program(progId)
    for s in STORE["students"].values():
        if s["program_id"] == prog["id"] and s["student_external_id"] == ext_id:
            fail("ERR_INVALID_REQUEST", 400,
                 "student_external_id must be unique within the program")
    rec = base_record()
    rec.update({
        "program_id": prog["id"],
        "student_external_id": ext_id,
        "full_name": full_name,
        "grade_level": grade_level,
        "free_lunch_eligible": free_lunch,
        "family_agreement_status": "PENDING",
        "insurance_enrolled": False,
        "financial_posture": "CLEAR",
        "outstanding_balance_cents": 0,
        "lifetime_damage_count": 0,
        "status": "ENROLLED",
    })
    STORE["students"][rec["id"]] = rec
    # FamilyAgreement row auto-created alongside (PRD 3.2).
    ag = base_record(with_version=False)
    ag.update({
        "student_account_id": rec["id"],
        "acceptable_use_version": None,
        "signed_by_guardian_name": None,
        "signed_at": None,
        "signature_state": "PENDING",
    })
    STORE["agreements"][ag["id"]] = ag
    return ok_object(student_json(rec), 201)


@bp.get("/api/programs/<progId>/students")
def list_students(progId):
    auth(STUDENT_READ)
    prog = get_program(progId)
    fp, fas, st = _q("financial_posture"), _q("family_agreement_status"), _q("status")
    recs = [s for s in STORE["students"].values()
            if s["program_id"] == prog["id"]
            and (fp is None or s["financial_posture"] == fp)
            and (fas is None or s["family_agreement_status"] == fas)
            and (st is None or s["status"] == st)]
    return list_response(recs, student_json)


@bp.get("/api/programs/<progId>/students/<studentId>")
def get_student_route(progId, studentId):
    uid, role = auth(STUDENT_READ_FAMILY)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    return ok_object(student_json(get_student(studentId, prog)))


def _leave_program(progId, studentId, target):
    b = body()
    reject_stray_occ(b)
    auth(["Registrar"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    if stu["status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", 409, "Student must be ENROLLED")
    for a in STORE["assignments"].values():
        if a["student_account_id"] == stu["id"] and a["status"] in ("ACTIVE", "OVERDUE"):
            fail("ERR_OPEN_ASSIGNMENTS", 409,
                 "Student still has ACTIVE or OVERDUE assignments")
    if stu["financial_posture"] != "CLEAR":
        fail("ERR_FEES_OUTSTANDING", 409,
             "financial_posture must be CLEAR to withdraw or graduate")
    stu["status"] = target
    touch(stu)
    return ok_object(student_json(stu))


@bp.post("/api/programs/<progId>/students/<studentId>/withdraw")
def withdraw_student(progId, studentId):
    return _leave_program(progId, studentId, "WITHDRAWN")


@bp.post("/api/programs/<progId>/students/<studentId>/graduate")
def graduate_student(progId, studentId):
    return _leave_program(progId, studentId, "GRADUATED")


@bp.get("/api/programs/<progId>/students/<studentId>/asset-units")
def list_student_units(progId, studentId):
    uid, role = auth(STUDENT_READ_FAMILY)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    recs = [u for u in STORE["units"].values()
            if u["assigned_to_student_id"] == stu["id"]]
    return list_response(recs, unit_json)


# ------------------------------------------------------ family agreement ---
@bp.get("/api/programs/<progId>/students/<studentId>/family-agreement")
def get_family_agreement(progId, studentId):
    uid, role = auth(AGREEMENT_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    recs = [a for a in STORE["agreements"].values() if a["student_account_id"] == stu["id"]]
    return list_response(recs, agreement_json)


def _agreement_action(progId, studentId, action):
    if action == "sign":
        b = body()
        aup = req_str(b, "acceptable_use_version")
        guardian = req_str(b, "signed_by_guardian_name")
        reject_stray_occ(b)
    else:
        b = body()
        reject_stray_occ(b)
        aup = guardian = None
    uid, role = auth(["Family"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    ag = None
    for a in STORE["agreements"].values():
        if a["student_account_id"] == stu["id"]:
            ag = a
            break
    if ag is None:
        fail("ERR_AGREEMENT_NOT_FOUND", 404, "No family agreement exists for this student")
    if stu["status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", 409, "Operation requires an ENROLLED student")
    if ag["signature_state"] != "PENDING":
        fail("ERR_INVALID_STATE", 409, "Agreement must be PENDING")
    if action == "sign":
        ag["acceptable_use_version"] = aup
        ag["signed_by_guardian_name"] = guardian
        ag["signed_at"] = now()
        ag["signature_state"] = "SIGNED"
        stu["family_agreement_status"] = "SIGNED"
    else:
        ag["signature_state"] = "DECLINED"
        stu["family_agreement_status"] = "DECLINED"
    touch(stu)
    return ok_object(agreement_json(ag))


@bp.post("/api/programs/<progId>/students/<studentId>/family-agreement/sign")
def sign_agreement(progId, studentId):
    return _agreement_action(progId, studentId, "sign")


@bp.post("/api/programs/<progId>/students/<studentId>/family-agreement/decline")
def decline_agreement(progId, studentId):
    return _agreement_action(progId, studentId, "decline")


# ---------------------------------------------------------- insurance ------
@bp.post("/api/programs/<progId>/students/<studentId>/insurance-policies")
def create_policy(progId, studentId):
    b = body()
    premium = req_int(b, "premium_cents", minimum=0)
    deductible = req_int(b, "deductible_cents", minimum=0)
    cap = req_int(b, "coverage_cap_cents", minimum=0)
    year = req_str(b, "academic_year")
    reject_stray_occ(b)
    uid, role = auth(["Family"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    rec = base_record()
    rec.update({
        "student_account_id": stu["id"],
        "premium_cents": premium,
        "deductible_cents": deductible,
        "coverage_cap_cents": cap,
        "academic_year": year,
        "status": "QUOTED",
        "_cumulative_payouts_cents": 0,
    })
    STORE["policies"][rec["id"]] = rec
    return ok_object(policy_json(rec), 201)


@bp.get("/api/programs/<progId>/students/<studentId>/insurance-policies")
def list_policies(progId, studentId):
    uid, role = auth(POLICY_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    st = _q("status")
    recs = [p for p in STORE["policies"].values()
            if p["student_account_id"] == stu["id"]
            and (st is None or p["status"] == st)]
    return list_response(recs, policy_json)


@bp.get("/api/programs/<progId>/students/<studentId>/insurance-policies/<policyId>")
def get_policy_route(progId, studentId, policyId):
    uid, role = auth(POLICY_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    return ok_object(policy_json(get_policy(policyId, stu)))


@bp.post("/api/programs/<progId>/students/<studentId>/insurance-policies/<policyId>/activate")
def activate_policy(progId, studentId, policyId):
    b = body()
    reject_stray_occ(b)
    uid, role = auth(["Family"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    pol = get_policy(policyId, stu)
    if pol["status"] != "QUOTED":
        fail("ERR_INVALID_STATE", 409, "Policy must be QUOTED to activate")
    if stu["family_agreement_status"] != "SIGNED":
        fail("ERR_AGREEMENT_NOT_SIGNED", 409, "Family agreement must be SIGNED")
    for p in STORE["policies"].values():
        if p["student_account_id"] == stu["id"] and p["status"] == "ACTIVE" and p["id"] != pol["id"]:
            fail("ERR_ACTIVE_POLICY_EXISTS", 409, "Student already has an ACTIVE policy")
    if pol["academic_year"] != prog["school_year"]:
        fail("ERR_POLICY_YEAR_MISMATCH", 409,
             "academic_year must equal the program school_year")
    pol["status"] = "ACTIVE"
    touch(pol)
    stu["insurance_enrolled"] = True
    touch(stu)
    return ok_object(policy_json(pol))


@bp.post("/api/programs/<progId>/students/<studentId>/insurance-policies/<policyId>/cancel")
def cancel_policy(progId, studentId, policyId):
    b = body()
    reject_stray_occ(b)
    uid, role = auth(["Family"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    pol = get_policy(policyId, stu)
    if pol["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "Policy must be ACTIVE to cancel")
    for f in STORE["fees"].values():
        if (f.get("_insurance_policy_id") == pol["id"] and f["status"] == "APPEALED"):
            fail("ERR_PENDING_APPEAL_BLOCKS_CANCEL", 409,
                 "An appeal is pending on a fee tied to a damage report under this policy")
    pol["status"] = "CANCELLED"
    touch(pol)
    stu["insurance_enrolled"] = False
    touch(stu)
    return ok_object(policy_json(pol))


@bp.post("/api/programs/<progId>/expire-insurance-policies")
def expire_policies(progId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    student_ids = {s["id"] for s in STORE["students"].values() if s["program_id"] == prog["id"]}
    expired = []
    for p in STORE["policies"].values():
        if p["student_account_id"] in student_ids and p["status"] == "ACTIVE":
            p["status"] = "EXPIRED"
            touch(p)
            expired.append(p["id"])
            stu = STORE["students"].get(p["student_account_id"])
            if stu is not None:
                stu["insurance_enrolled"] = False
                touch(stu)
    expired.sort()
    return ok_object({"expired_count": len(expired), "expired_policy_ids": expired})
