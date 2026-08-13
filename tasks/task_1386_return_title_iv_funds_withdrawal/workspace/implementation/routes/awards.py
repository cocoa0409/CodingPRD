"""Aid awards and disbursements."""

import uuid

import clock
import db
import errors
import serializers
from flask import Blueprint, request
from middleware import (ALL_ROLES, get_auth, require_roles, parse_json_body,
                        parse_pagination)
from response import success_object, success_list
from services import calc
from services.term_days import date_str

bp = Blueprint("awards", __name__)

PROGRAMS = ("PELL_GRANT", "SUBSIDIZED_LOAN", "UNSUBSIDIZED_LOAN", "PLUS_LOAN")


def _get_award_or_404(award_id):
    award = db.awards.get(award_id)
    if award is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "award not found")
    return award


@bp.post("/r2t4/enrollments/<enrollment_id>/awards")
def create_award(enrollment_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "enrollment not found")
    body = parse_json_body()

    program = body.get("program")
    amount = body.get("amount_cents")
    if program is None or amount is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "program and amount_cents are required")
    if program not in PROGRAMS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "program must be one of PELL_GRANT, SUBSIDIZED_LOAN, "
                           "UNSUBSIDIZED_LOAN, PLUS_LOAN")
    if not isinstance(amount, int) or isinstance(amount, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "amount_cents must be an integer")
    if amount <= 0:
        errors.raise_error(errors.ERR_INVALID_FIELD, "amount_cents must be positive")

    is_grant = program == "PELL_GRANT"
    award = {
        "id": str(uuid.uuid4()),
        "enrollment_id": enrollment_id,
        "program": program,
        "amount_cents": amount,
        "is_grant": is_grant,
        "status": "ACCEPTED" if is_grant else "OFFERED",
        "disbursed_amount_cents": 0,
        "scheduled_amount_cents": 0,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.awards[award["id"]] = award
    return success_object(serializers.award(award), status_code=201)


@bp.get("/r2t4/awards/<award_id>")
def get_award(award_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(serializers.award(_get_award_or_404(award_id)))


@bp.post("/r2t4/awards/<award_id>/accept")
def accept_award(award_id):
    auth = get_auth()
    require_roles(auth, ["Student"])
    parse_json_body()
    award = _get_award_or_404(award_id)
    enrollment = db.enrollments[award["enrollment_id"]]
    if enrollment["student_id"] != auth.user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_MISMATCH,
                           "students may only accept their own awards")
    if award["status"] != "OFFERED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only an OFFERED award can be accepted")
    award["status"] = "ACCEPTED"
    award["version"] += 1
    award["updated_at"] = clock.now_iso()
    return success_object(serializers.award(award))


@bp.post("/r2t4/awards/<award_id>/cancel")
def cancel_award(award_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    parse_json_body()
    award = _get_award_or_404(award_id)
    if award["status"] == "CANCELLED":
        errors.raise_error(errors.ERR_INVALID_STATE, "award is already cancelled")
    if award["disbursed_amount_cents"] > 0:
        errors.raise_error(errors.ERR_AWARD_HAS_DISBURSEMENTS,
                           "an award with disbursed funds cannot be cancelled")
    for d in db.disbursements.values():
        if d["award_id"] == award["id"] and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            d["updated_at"] = clock.now_iso()
            d["version"] += 1
            award["scheduled_amount_cents"] -= d["amount_cents"]
    award["status"] = "CANCELLED"
    award["version"] += 1
    award["updated_at"] = clock.now_iso()
    return success_object(serializers.award(award))


@bp.post("/r2t4/awards/<award_id>/disbursements")
def create_disbursement(award_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    award = _get_award_or_404(award_id)
    body = parse_json_body()
    amount = body.get("amount_cents")
    if amount is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "amount_cents is required")
    if not isinstance(amount, int) or isinstance(amount, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "amount_cents must be an integer")
    if amount <= 0:
        errors.raise_error(errors.ERR_INVALID_FIELD, "amount_cents must be positive")

    if award["status"] == "CANCELLED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "cannot schedule a disbursement on a cancelled award")
    if award["scheduled_amount_cents"] + award["disbursed_amount_cents"] + amount \
            > award["amount_cents"]:
        errors.raise_error(errors.ERR_DISBURSEMENT_EXCEEDS_AWARD,
                           "scheduled + disbursed + new amount exceeds the award amount")

    disb = {
        "id": str(uuid.uuid4()),
        "award_id": award["id"],
        "pwd_offer_id": None,
        "amount_cents": amount,
        "status": "SCHEDULED",
        "disbursed_on": None,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.disbursements[disb["id"]] = disb
    award["scheduled_amount_cents"] += amount
    award["updated_at"] = clock.now_iso()
    return success_object(serializers.disbursement(disb), status_code=201)


@bp.get("/r2t4/disbursements")
def list_disbursements():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.disbursements.values())
    award_id = request.args.get("award_id")
    pwd_offer_id = request.args.get("pwd_offer_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [d for d in items if d["award_id"] == award_id]
    if pwd_offer_id is not None:
        items = [d for d in items if d.get("pwd_offer_id") == pwd_offer_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.disbursement(d) for d in page],
                        total, limit, offset)


@bp.get("/r2t4/disbursements/<disbursement_id>")
def get_disbursement(disbursement_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    disb = db.disbursements.get(disbursement_id)
    if disb is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "disbursement not found")
    return success_object(serializers.disbursement(disb))


@bp.post("/r2t4/disbursements/<disbursement_id>/disburse")
def release_disbursement(disbursement_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    parse_json_body()
    disb = db.disbursements.get(disbursement_id)
    if disb is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "disbursement not found")
    award = db.awards[disb["award_id"]]
    enrollment = db.enrollments[award["enrollment_id"]]

    if disb["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only a SCHEDULED disbursement can be released")
    if award["status"] != "ACCEPTED":
        errors.raise_error(errors.ERR_AWARD_NOT_ACCEPTED,
                           "the award is not in ACCEPTED status")

    active_case = None
    case_id = enrollment.get("current_withdrawal_case_id")
    if case_id:
        candidate = db.withdrawal_cases.get(case_id)
        if candidate is not None and candidate["status"] in ("OPEN", "CALCULATED"):
            active_case = candidate
    if active_case is not None:
        errors.raise_error(errors.ERR_DISBURSEMENT_BLOCKED_BY_CASE,
                           "a withdrawal case is active for this enrollment")

    disb["status"] = "DISBURSED"
    disb["disbursed_on"] = date_str(clock.current_date())
    disb["version"] += 1
    disb["updated_at"] = clock.now_iso()
    award["disbursed_amount_cents"] += disb["amount_cents"]
    award["scheduled_amount_cents"] -= disb["amount_cents"]
    award["updated_at"] = clock.now_iso()
    calc.post_entry(enrollment["id"], "AID_CREDIT", -disb["amount_cents"],
                    source_ref=disb["id"])
    calc.recompute_balance(enrollment["id"])
    return success_object(serializers.disbursement(disb))
