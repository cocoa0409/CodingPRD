"""PaymentArrangement endpoints (PRD 3.9)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import bad, body, guard, opt_bool, opt_int, present, req_enum, req_id, req_int, req_str
from routes.common import ARRANGEMENT_TYPES, body_fk, one, path_get, require_owner
from services import calc, derive

bp = Blueprint("arrangements", __name__)


@bp.post("/payment-arrangements")
@guard("Taxpayer", "CollectionsAgent")
def request_arrangement():
    data = body()
    assessment_id = req_id(data, "assessment_id")
    arrangement_type = req_enum(data, "arrangement_type", ARRANGEMENT_TYPES)
    monthly = opt_int(data, "monthly_installment_cents", 1)
    term = opt_int(data, "term_months", 1, 72)
    offer = opt_int(data, "offer_amount_cents", 1)
    hardship = opt_bool(data, "hardship_documented", False)

    if arrangement_type == "INSTALLMENT_PLAN":
        if monthly is None:
            bad("monthly_installment_cents is required on an INSTALLMENT_PLAN.")
        if term is None:
            bad("term_months is required on an INSTALLMENT_PLAN.")
        if present(data, "offer_amount_cents"):
            bad("offer_amount_cents is not accepted on an INSTALLMENT_PLAN.")
        scheduled = monthly * term
    else:
        if offer is None:
            bad("offer_amount_cents is required on an OFFER_IN_COMPROMISE.")
        if present(data, "monthly_installment_cents") or present(data, "term_months"):
            bad("monthly_installment_cents and term_months are not accepted on an "
                "OFFER_IN_COMPROMISE.")
        scheduled = offer

    assessment = body_fk("assessments", assessment_id)
    holder = derive.taxpayer_of_assessment(assessment)
    require_owner(holder["id"] if holder else None)

    rec = db.new_record(
        {
            "assessment_id": assessment["id"],
            "arrangement_type": arrangement_type,
            "status": "REQUESTED",
            "monthly_installment_cents": monthly if arrangement_type == "INSTALLMENT_PLAN" else None,
            "term_months": term if arrangement_type == "INSTALLMENT_PLAN" else None,
            "offer_amount_cents": offer if arrangement_type == "OFFER_IN_COMPROMISE" else None,
            "hardship_documented": bool(hardship),
            "scheduled_total_cents": scheduled,
            "payments_made_count": 0,
            "amount_paid_cents": 0,
            "approved_at": None,
            "default_reason": None,
        }
    )
    db.insert("payment_arrangements", rec)
    return one("payment_arrangements", rec, 201)


@bp.get("/payment-arrangements/<rid>")
@guard("CollectionsAgent", "AuditSupervisor", "Taxpayer")
def read_arrangement(rid):
    return one("payment_arrangements", path_get("payment_arrangements", rid))


@bp.post("/payment-arrangements/<rid>/approve")
@guard("CollectionsAgent")
def approve_arrangement(rid):
    arrangement = path_get("payment_arrangements", rid)
    body()
    if arrangement["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")

    assessment = db.get("assessments", arrangement["assessment_id"])
    if assessment is None:
        raise ApiError("ERR_INVALID_STATE")
    if derive.has_open_proceeding(assessment["id"]):
        raise ApiError("ERR_APPEAL_PENDING")
    if assessment["status"] not in ("ISSUED", "FINAL"):
        raise ApiError("ERR_APPEAL_PENDING")
    if assessment["collection_status"] not in ("DUE", "REFERRED"):
        raise ApiError("ERR_INVALID_STATE")

    derive.refresh_assessment(assessment)
    balance = int(assessment["balance_due_cents"])
    if arrangement["arrangement_type"] == "INSTALLMENT_PLAN":
        if int(arrangement["scheduled_total_cents"]) < balance:
            raise ApiError("ERR_PLAN_UNDERFUNDED")
    else:
        if not arrangement["hardship_documented"]:
            raise ApiError("ERR_HARDSHIP_NOT_DOCUMENTED")
        if int(arrangement["offer_amount_cents"]) * 10000 < calc.MIN_OIC_BP * balance:
            raise ApiError("ERR_OFFER_BELOW_MINIMUM")

    arrangement["status"] = "APPROVED"
    arrangement["approved_at"] = db.clock_instant_str()
    db.touch(arrangement)
    assessment["collection_status"] = "ARRANGED"
    db.touch(assessment)
    return one("payment_arrangements", arrangement)


@bp.post("/payment-arrangements/<rid>/payments")
@guard("Taxpayer", "CollectionsAgent")
def record_payment(rid):
    arrangement = path_get("payment_arrangements", rid)
    data = body()
    amount = req_int(data, "amount_cents", 1)

    if arrangement["status"] != "APPROVED":
        raise ApiError("ERR_ARRANGEMENT_NOT_ACTIVE")
    assessment = db.get("assessments", arrangement["assessment_id"])
    if assessment is None:
        raise ApiError("ERR_INVALID_STATE")

    arrangement["amount_paid_cents"] = int(arrangement["amount_paid_cents"]) + amount
    arrangement["payments_made_count"] = int(arrangement["payments_made_count"]) + 1
    assessment["amount_paid_cents"] = int(assessment["amount_paid_cents"]) + amount
    derive.refresh_assessment(assessment)

    performed = False
    if arrangement["arrangement_type"] == "INSTALLMENT_PLAN":
        performed = int(assessment["balance_due_cents"]) <= 0
    else:
        performed = int(arrangement["amount_paid_cents"]) >= int(arrangement["offer_amount_cents"])
        if performed and int(assessment["balance_due_cents"]) > 0:
            derive.post_adjustment(
                assessment,
                "OIC_WRITEOFF",
                int(assessment["balance_due_cents"]),
                "SYSTEM",
            )
            derive.refresh_assessment(assessment)

    if performed:
        arrangement["status"] = "COMPLETED"
        derive.cascade_satisfied(assessment)
    else:
        derive.settle_balance(assessment)
    db.touch(arrangement)
    db.touch(assessment)
    return one("payment_arrangements", arrangement)


@bp.post("/payment-arrangements/<rid>/default")
@guard("CollectionsAgent")
def default_arrangement(rid):
    arrangement = path_get("payment_arrangements", rid)
    data = body()
    reason = req_str(data, "default_reason", 1, None)

    if arrangement["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    assessment = db.get("assessments", arrangement["assessment_id"])
    if assessment is None:
        raise ApiError("ERR_INVALID_STATE")
    derive.refresh_assessment(assessment)
    if int(assessment["balance_due_cents"]) <= 0:
        raise ApiError("ERR_INVALID_STATE")

    arrangement["status"] = "DEFAULTED"
    arrangement["default_reason"] = reason
    db.touch(arrangement)

    fee = calc.collection_fee(int(assessment["balance_due_cents"]))
    assessment["collection_status"] = "REFERRED"
    derive.post_adjustment(assessment, "COLLECTION_FEE", fee, "SYSTEM")
    derive.refresh_assessment(assessment)
    db.touch(assessment)
    holder = derive.taxpayer_of_assessment(assessment)
    if holder is not None and holder["compliance_status"] != "DELINQUENT":
        holder["compliance_status"] = "DELINQUENT"
        db.touch(holder)
    return one("payment_arrangements", arrangement)
