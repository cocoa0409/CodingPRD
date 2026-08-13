"""Return obligations and post-withdrawal offers."""

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

bp = Blueprint("obligations", __name__)


# ---------------------------------------------------------------- obligations

@bp.post("/r2t4/return-obligations/<obligation_id>/record-return")
def record_return(obligation_id):
    auth = get_auth()
    require_roles(auth, ["BursarClerk", "FinancialAidOfficer"])
    body = parse_json_body()
    obligation = db.obligations.get(obligation_id)
    if obligation is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "return obligation not found")

    # Priority 6: state.
    if obligation["status"] == "RETURNED":
        errors.raise_error(errors.ERR_OBLIGATION_ALREADY_RETURNED,
                           "obligation is already returned")
    if obligation["status"] == "VOIDED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "a voided obligation cannot be recorded")

    amount = body.get("amount_cents")
    if amount is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "amount_cents is required")
    if not isinstance(amount, int) or isinstance(amount, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "amount_cents must be an integer")

    returned_on = body.get("returned_on")
    if returned_on is not None:
        from services.term_days import parse_date
        if parse_date(returned_on) is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "returned_on must be an ISO date (YYYY-MM-DD)")

    # Priority 11: segregation of duties — FAO who calculated the case may not
    # record the SCHOOL-party return.
    case = db.withdrawal_cases.get(obligation["withdrawal_case_id"])
    if (obligation["party"] == "SCHOOL"
            and auth.role == "FinancialAidOfficer"
            and case is not None
            and auth.user_id == case.get("calculated_by_user_id")):
        errors.raise_error(errors.ERR_SEGREGATION_OF_DUTIES,
                           "the officer who calculated a case may not record its "
                           "school-party return")

    # Priority 12: exact amount.
    if amount != obligation["amount_cents"]:
        errors.raise_error(errors.ERR_RETURN_AMOUNT_MISMATCH,
                           "amount_cents must equal the obligation amount exactly")

    obligation["status"] = "RETURNED"
    obligation["returned_at"] = clock.now_iso()
    obligation["returned_amount_cents"] = amount
    obligation["recorded_by_user_id"] = auth.user_id
    obligation["version"] += 1
    obligation["updated_at"] = clock.now_iso()

    if case is not None:
        calc.evaluate_auto_close(case["id"])

    return success_object(serializers.obligation(obligation))


# ---------------------------------------------------------------- offers

@bp.get("/r2t4/post-withdrawal-offers")
def list_offers():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.offers.values())
    award_id = request.args.get("award_id")
    case_id = request.args.get("withdrawal_case_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [o for o in items if o["award_id"] == award_id]
    if case_id is not None:
        items = [o for o in items if o["withdrawal_case_id"] == case_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.offer(o) for o in page], total, limit, offset)


def _get_offer_or_404(offer_id):
    offer = db.offers.get(offer_id)
    if offer is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "post-withdrawal offer not found")
    return offer


@bp.get("/r2t4/post-withdrawal-offers/<offer_id>")
def get_offer(offer_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(serializers.offer(_get_offer_or_404(offer_id)))


def _respond_to_offer(offer_id, auth, accept: bool):
    offer = _get_offer_or_404(offer_id)
    case = db.withdrawal_cases[offer["withdrawal_case_id"]]
    enrollment = db.enrollments[case["enrollment_id"]]
    award = db.awards[offer["award_id"]]

    if enrollment["student_id"] != auth.user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_MISMATCH,
                           "students may only respond to their own offers")
    if offer["status"] != "SENT":
        errors.raise_error(errors.ERR_OFFER_NOT_RESPONDABLE,
                           "offer is not in SENT status")

    offer["responded_at"] = clock.now_iso()
    if accept:
        offer["status"] = "ACCEPTED"
        import uuid as _uuid_mod
        disb = {
            "id": str(_uuid_mod.uuid4()),
            "award_id": award["id"],
            "pwd_offer_id": offer["id"],
            "amount_cents": offer["amount_cents"],
            "status": "DISBURSED",
            "disbursed_on": date_str(clock.current_date()),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.disbursements[disb["id"]] = disb
        award["disbursed_amount_cents"] += offer["amount_cents"]
        award["updated_at"] = clock.now_iso()
        award["version"] += 1
        calc.post_entry(enrollment["id"], "AID_CREDIT", -offer["amount_cents"],
                        source_ref=disb["id"])
        calc.recompute_balance(enrollment["id"])
    else:
        offer["status"] = "DECLINED"

    offer["version"] += 1
    offer["updated_at"] = clock.now_iso()
    calc.evaluate_auto_close(case["id"])
    return offer


@bp.post("/r2t4/post-withdrawal-offers/<offer_id>/accept")
def accept_offer(offer_id):
    auth = get_auth()
    require_roles(auth, ["Student"])
    parse_json_body()
    offer = _respond_to_offer(offer_id, auth, accept=True)
    return success_object(serializers.offer(offer))


@bp.post("/r2t4/post-withdrawal-offers/<offer_id>/decline")
def decline_offer(offer_id):
    auth = get_auth()
    require_roles(auth, ["Student"])
    parse_json_body()
    offer = _respond_to_offer(offer_id, auth, accept=False)
    return success_object(serializers.offer(offer))
