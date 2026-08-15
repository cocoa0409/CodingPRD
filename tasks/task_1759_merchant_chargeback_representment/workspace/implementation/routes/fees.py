"""FeeAssessment endpoints (PRD 3.8) — manual ARBITRATION_FEE creation,
segregation-of-duties waiver, settlement from clearing."""

from flask import Blueprint, g, request

from clock import CLOCK
from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_fee_assessment, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_fee_assessment
from util import Body, FEE_KINDS, FEE_STATUSES, filter_enum

bp = Blueprint("fees", __name__)


@bp.post("/acquirer/fee-assessments")
def create_fee_assessment():
    authenticate(("FinanceOps",))
    b = Body(json_body())
    merchant_id = b.req_str("merchant_id")
    kind_raw = b.d.get("kind")
    amount_cents = b.req_int("amount_cents")
    chargeback_id = b.opt_str("chargeback_id")
    enrollment_id = b.opt_str("enrollment_id")

    # Priority 3: body-referenced ids.
    merchant = None
    if merchant_id is not None:
        merchant = get_or_404(db.merchants, merchant_id, "Merchant")
    if chargeback_id is not None:
        get_or_404(db.chargebacks, chargeback_id, "Chargeback")
    if enrollment_id is not None:
        get_or_404(db.program_enrollments, enrollment_id, "ProgramEnrollment")

    # Priority 11: payload shape. Manual creation is restricted to ARBITRATION_FEE:
    # a valid enum member of another kind is ERR_INVALID_REQUEST; a non-member is ERR_INVALID_ENUM.
    if kind_raw is not None and kind_raw in FEE_KINDS and kind_raw != "ARBITRATION_FEE":
        b._fail(("ERR_INVALID_REQUEST", 400), "Only ARBITRATION_FEE may be created via the manual endpoint")
    else:
        b.req_enum("kind", FEE_KINDS)
    if amount_cents is not None and amount_cents <= 0:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'amount_cents' must be > 0")
    b.raise_pending()

    fee = new_fee_assessment(merchant["id"], chargeback_id, enrollment_id, "ARBITRATION_FEE",
                             amount_cents, g.uid)
    db.fee_assessments[fee["id"]] = fee
    return ok_object(serialize_fee_assessment(fee), status=201)


@bp.get("/acquirer/fee-assessments")
def list_fee_assessments():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    chargeback_id = request.args.get("chargeback_id")
    enrollment_id = request.args.get("enrollment_id")
    status = filter_enum(request.args, "status", FEE_STATUSES)
    records = list(db.fee_assessments.values())
    if is_merchant_user():
        records = [f for f in records if f["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [f for f in records if f["merchant_id"] == merchant_id]
    if chargeback_id is not None:
        records = [f for f in records if f["chargeback_id"] == chargeback_id]
    if enrollment_id is not None:
        records = [f for f in records if f["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [f for f in records if f["status"] == status]
    return list_response(records, serialize_fee_assessment)


@bp.get("/acquirer/fee-assessments/<fid>")
def get_fee_assessment(fid):
    authenticate(ALL_ROLES)
    fee = get_or_404(db.fee_assessments, fid, "FeeAssessment")
    hide_if_cross_merchant(fee["merchant_id"])
    return ok_object(serialize_fee_assessment(fee))


@bp.post("/acquirer/fee-assessments/<fid>/waive")
def waive_fee(fid):
    authenticate(("FinanceOps",))
    fee = get_or_404(db.fee_assessments, fid, "FeeAssessment")
    # Priority 5: fee must still be ASSESSED.
    if fee["status"] != "ASSESSED":
        raise ApiError(409, "ERR_INVALID_FEE_STATE", "Only an ASSESSED fee can be waived")
    # Priority 6: segregation of duties (system-assessed fees exempt).
    if fee["assessed_by_user_id"] != "system" and fee["assessed_by_user_id"] == g.uid:
        raise ApiError(403, "ERR_SEGREGATION_OF_DUTIES",
                       "A FinanceOps user cannot waive a fee they assessed themselves")
    fee["status"] = "WAIVED"
    fee["waived_by_user_id"] = g.uid
    fee["waived_at"] = CLOCK.now()
    touch(fee)
    return ok_object(serialize_fee_assessment(fee))


@bp.post("/acquirer/fee-assessments/<fid>/settle")
def settle_fee(fid):
    authenticate(("FinanceOps",))
    fee = get_or_404(db.fee_assessments, fid, "FeeAssessment")
    if fee["status"] != "ASSESSED":
        raise ApiError(409, "ERR_INVALID_FEE_STATE", "Only an ASSESSED fee can be settled")
    merchant = db.merchants[fee["merchant_id"]]
    merchant["clearing_balance_cents"] -= fee["amount_cents"]
    touch(merchant)
    fee["status"] = "SETTLED"
    fee["settled_at"] = CLOCK.now()
    touch(fee)
    return ok_object(serialize_fee_assessment(fee))
