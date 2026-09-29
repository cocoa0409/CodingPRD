"""Origination, the pinned pricing chain, disbursement, servicing and charge-off."""
from datetime import timedelta

import calc
import services as svc
import shape
from auth import authenticate, scope, segregation
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, date_floor, db, fmt_date, now, ordered, touch

bp = Blueprint("loans", __name__)

LOAN_READ_ROLES = ("InstitutionOfficer", "CreditUnderwriter", "CreditCommittee",
                   "ComplianceAnalyst", "Borrower")
LOAN_LIST_ROLES = ("InstitutionOfficer", "CreditUnderwriter", "CreditCommittee",
                   "ComplianceAnalyst")
DECISIONS = ("APPROVE", "DECLINE")
DISBURSABLE_UNDERWRITING = ("APPROVED", "CLOSED")
DISBURSABLE_SERVICING = ("NOT_DISBURSED", "CURRENT", "DELINQUENT_30",
                         "DELINQUENT_60", "DELINQUENT_90")
PAYABLE_SERVICING = ("CURRENT", "DELINQUENT_30", "DELINQUENT_60", "DELINQUENT_90")


def _owning(loan_id):
    row = db.loans.get(loan_id)
    return row["institution_id"] if row else None


@bp.post("/loans")
def file_loan():
    caller = authenticate(("InstitutionOfficer",))
    data = shape.body()
    institution_id = shape.body_id(data, "institution_id")
    scope(caller, institution_id)
    inst = svc.get_institution(institution_id)
    borrower = svc.get_borrower(shape.body_id(data, "borrower_id"), inst["id"])
    product = svc.get_product(shape.body_id(data, "product_id"), inst["id"])
    refinance_id = shape.body_id(data, "refinance_of_loan_id")
    if refinance_id is not None:
        prior = svc.get_loan(refinance_id)
        if prior["borrower_id"] != borrower["id"]:
            # It must name *another loan of the same borrower*.
            fail("ERR_LOAN_NOT_FOUND")
    requested = shape.req_int(data, "requested_principal_cents", minimum=1)
    row = base_row()
    row.update({
        "institution_id": inst["id"],
        "borrower_id": borrower["id"],
        "product_id": product["id"],
        "refinance_of_loan_id": refinance_id,
        "requested_principal_cents": requested,
        "approved_principal_cents": None,
        "underwriting_state": "SCREENING",
        "servicing_state": "NOT_DISBURSED",
        "verified_monthly_income_cents": None,
        "existing_monthly_debt_cents": None,
        "credit_score_at_underwriting": None,
        "provisional_monthly_payment_cents": None,
        "dti_pct": None,
        "risk_grade": None,
        "risk_spread_bps": None,
        "ta_discount_bps": None,
        "final_rate_bps": None,
        "monthly_payment_cents": None,
        "principal_disbursed_cents": 0,
        "principal_repaid_cents": 0,
        "principal_outstanding_cents": 0,
        "charged_off_principal_cents": 0,
        "first_disbursed_on": None,
        "next_payment_due_on": None,
        "days_past_due": 0,
        "borrower_in_target_market_at_origination": False,
        "vintage_year": None,
        "underwritten_by_user_id": None,
        "decided_by_user_id": None,
        "decline_reason": None,
    })
    db.loans[row["id"]] = row
    return created(row)


@bp.get("/loans/<loan_id>")
def read_loan(loan_id):
    caller = authenticate(LOAN_READ_ROLES)
    scope(caller, _owning(loan_id))
    return ok(svc.get_loan(loan_id))


@bp.get("/loans")
def list_loans():
    caller = authenticate(LOAN_LIST_ROLES)
    institution_id = qs("institution_id")
    scope(caller, institution_id)
    limit, offset = pagination()
    rows = ordered(db.loans.values())
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    for name in ("borrower_id", "product_id", "refinance_of_loan_id",
                 "underwriting_state", "servicing_state"):
        value = qs(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return page(rows, limit, offset)


@bp.post("/loans/<loan_id>/underwrite")
def underwrite(loan_id):
    caller = authenticate(("CreditUnderwriter",))
    loan = svc.get_loan(loan_id)
    data = shape.body()
    income = shape.req_int(data, "verified_monthly_income_cents", minimum=0)
    debt = shape.req_int(data, "existing_monthly_debt_cents", minimum=0)
    score = shape.opt_int(data, "credit_score_at_underwriting")
    if loan["underwriting_state"] != "SCREENING":
        fail("ERR_INVALID_STATE_TRANSITION")
    product = svc.get_product(loan["product_id"])
    borrower = svc.get_borrower(loan["borrower_id"])
    # The pinned chain: the DTI is computed once, at step 2, and frozen there.
    provisional = calc.simple_declining_payment(
        loan["requested_principal_cents"], product["base_rate_bps"],
        product["term_months"])
    dti = calc.debt_to_income(debt, provisional, income)
    # The tier-and-DTI evaluation precedes the borrower-geocoded check (PRD 2.8).
    if dti is None or dti > product["max_dti_pct"]:
        fail("ERR_UNDERWRITING_TIER_UNMET")
    grade = calc.resolve_tier(score, dti, product, borrower["ta_hours_total"])
    if grade is None:
        fail("ERR_UNDERWRITING_TIER_UNMET")
    if borrower["geocode_state"] != "GEOCODED":
        fail("ERR_BORROWER_NOT_GEOCODED")
    spread = calc.RISK_SPREAD_BPS[grade]
    discount = calc.ta_discount_bps(borrower["ta_hours_total"])
    final_rate = product["base_rate_bps"] + spread - discount
    loan.update({
        "underwriting_state": "UNDERWRITING",
        "verified_monthly_income_cents": income,
        "existing_monthly_debt_cents": debt,
        "credit_score_at_underwriting": score,
        "provisional_monthly_payment_cents": provisional,
        "dti_pct": dti,
        "risk_grade": grade,
        "risk_spread_bps": spread,
        "ta_discount_bps": discount,
        "final_rate_bps": final_rate,
        "monthly_payment_cents": calc.simple_declining_payment(
            loan["requested_principal_cents"], final_rate,
            product["term_months"]),
        "underwritten_by_user_id": caller.user_id,
    })
    touch(loan)
    return ok(loan)


@bp.post("/loans/<loan_id>/decision")
def decide_loan(loan_id):
    caller = authenticate(("CreditCommittee",))
    existing = db.loans.get(loan_id)
    if existing is not None:
        segregation(caller, existing["underwritten_by_user_id"])
    loan = svc.get_loan(loan_id)
    data = shape.body()
    decision = shape.req_enum(data, "decision", DECISIONS)
    approved = shape.opt_int(data, "approved_principal_cents", minimum=1)
    reason = shape.opt_str(data, "decline_reason")
    if loan["underwriting_state"] != "UNDERWRITING":
        fail("ERR_LOAN_NOT_IN_UNDERWRITING")
    product = svc.get_product(loan["product_id"])
    if decision == "APPROVE":
        amount = approved if approved is not None else loan["requested_principal_cents"]
        if product["requires_ta_completion"] and not svc.ta_prerequisite_met(
                loan["borrower_id"]):
            fail("ERR_TA_PREREQUISITE_UNMET")
        if product["committed_principal_cents"] + amount > product["product_cap_cents"]:
            fail("ERR_PRODUCT_CAP_EXCEEDED")
        loan["underwriting_state"] = "APPROVED"
        loan["approved_principal_cents"] = amount
        loan["decided_by_user_id"] = caller.user_id
        touch(loan)
        svc.recompute_committed_principal(product)
    else:
        loan["underwriting_state"] = "DECLINED"
        loan["decline_reason"] = reason
        loan["decided_by_user_id"] = caller.user_id
        touch(loan)
    return ok(loan)


def _recompute_outstanding(loan):
    loan["principal_outstanding_cents"] = (loan["principal_disbursed_cents"]
                                           - loan["principal_repaid_cents"]
                                           - loan["charged_off_principal_cents"])


@bp.post("/loans/<loan_id>/disbursements")
def disburse(loan_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, _owning(loan_id))
    loan = svc.get_loan(loan_id)
    data = shape.body()
    amount = shape.req_int(data, "amount_cents", minimum=1)
    if (loan["underwriting_state"] not in DISBURSABLE_UNDERWRITING
            or loan["servicing_state"] not in DISBURSABLE_SERVICING):
        fail("ERR_INVALID_STATE_TRANSITION")
    approved = loan["approved_principal_cents"] or 0
    if loan["principal_disbursed_cents"] + amount > approved:
        fail("ERR_DISBURSEMENT_EXCEEDS_APPROVED")
    first_advance = loan["first_disbursed_on"] is None
    loan["principal_disbursed_cents"] = loan["principal_disbursed_cents"] + amount
    _recompute_outstanding(loan)
    if first_advance:
        # Dated by the logical clock, never by a request field.
        origination_date = date_floor(now())
        loan["first_disbursed_on"] = fmt_date(origination_date)
        loan["vintage_year"] = origination_date.year
        loan["next_payment_due_on"] = fmt_date(
            origination_date + timedelta(days=calc.PAYMENT_PERIOD_DAYS))
        borrower = db.borrowers.get(loan["borrower_id"])
        loan["borrower_in_target_market_at_origination"] = bool(
            borrower["in_target_market"]) if borrower else False
        loan["underwriting_state"] = "CLOSED"
        loan["servicing_state"] = "CURRENT"
    touch(loan)
    inst = svc.get_institution(loan["institution_id"])
    svc.recompute_reserve(inst)
    touch(inst)
    return ok(loan)


@bp.post("/loans/<loan_id>/payments")
def pay(loan_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, _owning(loan_id))
    loan = svc.get_loan(loan_id)
    data = shape.body()
    amount = shape.req_int(data, "amount_cents", minimum=1)
    if loan["servicing_state"] not in PAYABLE_SERVICING:
        fail("ERR_INVALID_STATE_TRANSITION")
    if amount > loan["principal_outstanding_cents"]:
        fail("ERR_PAYMENT_EXCEEDS_OUTSTANDING")
    was_delinquent = loan["servicing_state"] != "CURRENT"
    installment = loan["monthly_payment_cents"] or 0
    loan["principal_repaid_cents"] = loan["principal_repaid_cents"] + amount
    _recompute_outstanding(loan)
    cured = was_delinquent and amount >= installment
    next_due = fmt_date(date_floor(now()) + timedelta(days=calc.PAYMENT_PERIOD_DAYS))
    if cured:
        loan["servicing_state"] = "CURRENT"
        loan["days_past_due"] = 0
        loan["next_payment_due_on"] = next_due
    elif not was_delinquent:
        loan["next_payment_due_on"] = next_due
    if loan["principal_outstanding_cents"] == 0:
        loan["servicing_state"] = "PAID_OFF"
        loan["underwriting_state"] = "CLOSED"
        loan["next_payment_due_on"] = None
        loan["days_past_due"] = 0
    touch(loan)
    inst = svc.get_institution(loan["institution_id"])
    svc.recompute_reserve(inst)
    touch(inst)
    return ok(loan)


@bp.post("/loans/<loan_id>/charge-off")
def charge_off(loan_id):
    authenticate(("ComplianceAnalyst",))
    loan = svc.get_loan(loan_id)
    data = shape.body()
    reason = shape.req_str(data, "charge_off_reason", 1)
    if loan["servicing_state"] != "DELINQUENT_90":
        fail("ERR_LOAN_NOT_DELINQUENT_90")
    written_off = loan["principal_outstanding_cents"]
    loan["charged_off_principal_cents"] = (loan["charged_off_principal_cents"]
                                           + written_off)
    loan["principal_outstanding_cents"] = 0
    loan["servicing_state"] = "CHARGED_OFF"
    loan["underwriting_state"] = "CLOSED"
    loan["_charge_off_reason"] = reason  # not a declared Loan field; kept internal
    touch(loan)
    inst = svc.get_institution(loan["institution_id"])
    # The reserve absorbs the write-off first; the unabsorbed remainder is the
    # recorded deficit.
    prior_balance = inst["loss_reserve_balance_cents"]
    absorbed = prior_balance - written_off
    inst["loss_reserve_balance_cents"] = absorbed if absorbed > 0 else 0
    deficit = written_off - prior_balance
    inst["reserve_deficit_cents"] = deficit if deficit > 0 else 0
    svc.recompute_reserve(inst)
    touch(inst)
    return ok(loan)
