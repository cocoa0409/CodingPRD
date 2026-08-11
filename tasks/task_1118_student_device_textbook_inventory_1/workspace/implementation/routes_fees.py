"""FeeAssessment adjudication endpoints (PRD 3.7)."""
from flask import Blueprint, request

from core import (STORE, auth, body, fail, family_path_scope, fee_json,
                  get_fee, get_program, get_student, list_response, now,
                  ok_object, reject_stray_occ, recompute_posture, req_int,
                  touch, whole_days)

bp = Blueprint("fees", __name__)

FEE_READ = ["DistrictAdmin", "Registrar", "Family"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/api/programs/<progId>/students/<studentId>/fees")
def list_fees(progId, studentId):
    uid, role = auth(FEE_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    st, ft, src = _q("status"), _q("fee_type"), _q("source_damage_report_id")
    recs = [f for f in STORE["fees"].values()
            if f["student_account_id"] == stu["id"]
            and (st is None or f["status"] == st)
            and (ft is None or f["fee_type"] == ft)
            and (src is None or f["source_damage_report_id"] == src)]
    return list_response(recs, fee_json)


@bp.get("/api/programs/<progId>/students/<studentId>/fees/<feeId>")
def get_fee_route(progId, studentId, feeId):
    uid, role = auth(FEE_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    return ok_object(fee_json(get_fee(feeId, stu)))


def _load_fee(progId, studentId, feeId, allowed_roles):
    uid, role = auth(allowed_roles)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    fee = get_fee(feeId, stu)
    return stu, fee


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/appeal")
def appeal_fee(progId, studentId, feeId):
    b = body()
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["Family"])
    if fee["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE", 409, "Fee must be ASSESSED to appeal")
    if whole_days(fee["created_at"], now()) > 30:
        fail("ERR_APPEAL_WINDOW_CLOSED", 409,
             "Fees older than 30 days cannot be appealed")
    fee["status"] = "APPEALED"
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/appeal-grant")
def appeal_grant(progId, studentId, feeId):
    b = body()
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["DistrictAdmin"])
    if fee["status"] != "APPEALED":
        fail("ERR_INVALID_STATE", 409, "Fee must be APPEALED to grant the appeal")
    fee["status"] = "WAIVED"
    fee["waived_cents"] = fee["amount_cents"] - fee["paid_cents"]
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/appeal-deny")
def appeal_deny(progId, studentId, feeId):
    b = body()
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["DistrictAdmin"])
    if fee["status"] != "APPEALED":
        fail("ERR_INVALID_STATE", 409, "Fee must be APPEALED to deny the appeal")
    fee["status"] = "ASSESSED"
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/waive")
def waive_fee(progId, studentId, feeId):
    b = body()
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["DistrictAdmin"])
    if fee["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE", 409, "Fee must be ASSESSED to waive")
    if not stu["free_lunch_eligible"]:
        fail("ERR_WAIVER_NOT_ELIGIBLE", 422,
             "Waive requires the student to be free_lunch_eligible")
    if fee["fee_type"] not in ("DAMAGE", "LATE_RETURN"):
        fail("ERR_WAIVER_FORBIDDEN_FOR_FEE_TYPE", 422,
             "Only DAMAGE and LATE_RETURN fees can be waived")
    fee["status"] = "WAIVED"
    fee["waived_cents"] = fee["amount_cents"] - fee["paid_cents"]
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/settle")
def settle_fee(progId, studentId, feeId):
    b = body()
    payment = req_int(b, "payment_cents", minimum=0)
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["DistrictAdmin"])
    if fee["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE", 409, "Fee must be ASSESSED to settle")
    if fee["paid_cents"] + payment + fee["waived_cents"] < fee["amount_cents"]:
        fail("ERR_UNDERPAID", 422,
             "paid_cents + waived_cents must reach amount_cents to settle")
    fee["paid_cents"] += payment
    fee["status"] = "SETTLED"
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))


@bp.post("/api/programs/<progId>/students/<studentId>/fees/<feeId>/write-off")
def write_off_fee(progId, studentId, feeId):
    b = body()
    reject_stray_occ(b)
    stu, fee = _load_fee(progId, studentId, feeId, ["DistrictAdmin"])
    if fee["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE", 409, "Fee must be ASSESSED to write off")
    if stu["status"] not in ("WITHDRAWN", "GRADUATED"):
        fail("ERR_STUDENT_ACTIVE", 409,
             "An active student's fees cannot be written off")
    if whole_days(fee["created_at"], now()) < 180:
        fail("ERR_WRITE_OFF_TOO_EARLY", 409,
             "Fee must have been ASSESSED for at least 180 days")
    fee["status"] = "WRITTEN_OFF"
    touch(fee)
    recompute_posture(stu)
    return ok_object(fee_json(fee))
