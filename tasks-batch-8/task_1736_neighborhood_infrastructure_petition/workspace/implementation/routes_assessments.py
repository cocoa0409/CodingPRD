"""ParcelAssessment, InstallmentInvoice, and Payment endpoints (§3.8)."""
from flask import Blueprint

import errors
import services
import shape
from envelope import ok_object
from helpers import get_or_404, list_response, sort_created, sort_due_date
from security import ALL_ROLES, authenticate, require_role
from serializers import ser_assessment, ser_invoice, ser_payment
from store import STORE, iso, new_id, now, touch

bp = Blueprint("assessments", __name__)

_PAYABLE = ("LEVIED", "SETTLEMENT_DUE", "IN_REPAYMENT", "DELINQUENT")


def _assessment_or_404(aid):
    return get_or_404("assessments", aid, errors.ASSESSMENT_NOT_FOUND,
                      "Parcel assessment not found")


def _assessment_parcel(a):
    return STORE.parcels.get(a["parcel_id"])


@bp.route("/parcel-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    return ok_object(ser_assessment(_assessment_or_404(aid)))


@bp.route("/parcel-assessments/<aid>/select-payment-option", methods=["POST"])
def select_payment_option(aid):
    body = shape.get_body()
    option = shape.req_enum(body, "option", {"PREPAY_FULL", "INSTALLMENTS"})
    term_years = shape.opt_int(body, "term_years", None)
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    a = _assessment_or_404(aid)
    parcel = _assessment_parcel(a)
    if parcel is None or parcel["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the parcel's owner may select a payment option")
    if a["status"] != "LEVIED":
        errors.raise_err(errors.ASSESSMENT_NOT_LEVIED,
                         "Payment options may only be selected on a LEVIED assessment")
    if a["payment_option"] != "NONE":
        errors.raise_err(errors.ASSESSMENT_OPTION_ALREADY_SELECTED,
                         "A payment option has already been selected")
    d = STORE.districts[a["district_id"]]
    if d["payment_option_deadline"] is not None and now() > d["payment_option_deadline"]:
        errors.raise_err(errors.PAYMENT_OPTION_WINDOW_CLOSED,
                         "The payment-option window has closed")
    if option == "INSTALLMENTS":
        if term_years not in (5, 10):
            errors.raise_err(errors.TERM_NOT_ALLOWED,
                             "term_years must be 5 or 10 when option is INSTALLMENTS")
    else:  # PREPAY_FULL
        if term_years is not None:
            errors.raise_err(errors.TERM_NOT_ALLOWED,
                             "term_years must be absent when option is PREPAY_FULL")
    a["payment_option"] = option
    a["term_years"] = term_years if option == "INSTALLMENTS" else None
    a["option_selected_at"] = now()
    touch(a)
    return ok_object(ser_assessment(a))


@bp.route("/parcel-assessments/<aid>/payoff-quote", methods=["POST"])
def payoff_quote(aid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner", "FinanceOfficer"])
    a = _assessment_or_404(aid)
    if ctx.role == "PropertyOwner":
        parcel = _assessment_parcel(a)
        if parcel is None or parcel["owner_id"] != ctx.user_id:
            errors.raise_err(errors.NOT_RESOURCE_OWNER,
                             "Only the parcel's owner may request a payoff quote")
    d = STORE.districts[a["district_id"]]
    quote = services.payoff_quote(d, a, now())
    quote["as_of"] = iso(now())
    return ok_object(quote)


@bp.route("/parcel-assessments/<aid>/refund-credit", methods=["POST"])
def refund_credit(aid):
    body = shape.get_body()
    amount = shape.req_int(body, "amount_cents")
    ctx = authenticate()
    require_role(ctx, ["FinanceOfficer"])
    a = _assessment_or_404(aid)
    if amount <= 0 or amount > a["credit_balance_cents"]:
        errors.raise_err(errors.REFUND_EXCEEDS_CREDIT,
                         "Refund must be positive and no greater than the credit balance")
    a["credit_balance_cents"] -= amount
    a["total_refunded_cents"] += amount
    touch(a)
    return ok_object(ser_assessment(a))


@bp.route("/parcel-assessments/<aid>/invoices", methods=["GET"])
def assessment_invoices(aid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _assessment_or_404(aid)
    records = [i for i in STORE.invoices.values() if i["parcel_assessment_id"] == aid]
    return list_response(sort_due_date(records), ser_invoice, paginated=False)


@bp.route("/parcel-assessments/<aid>/payments", methods=["GET"])
def assessment_payments(aid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _assessment_or_404(aid)
    records = [p for p in STORE.payments.values() if p["parcel_assessment_id"] == aid]
    return list_response(sort_created(records), ser_payment, paginated=False)


# --- invoices ---

@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    inv = get_or_404("invoices", iid, errors.INVOICE_NOT_FOUND, "Invoice not found")
    return ok_object(ser_invoice(inv))


# --- payments ---

@bp.route("/payments", methods=["POST"])
def create_payment():
    body = shape.get_body()
    assessment_id = shape.req_str(body, "parcel_assessment_id")
    expected_version = shape.req_int(body, "expected_parcel_assessment_version")
    amount = shape.req_int(body, "amount_cents")
    method = shape.req_enum(body, "method", {"CHECK", "ACH", "CARD"})
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    a = _assessment_or_404(assessment_id)
    parcel = _assessment_parcel(a)
    if parcel is None or parcel["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the parcel's owner may pay the assessment")
    if expected_version != a["version"]:
        errors.raise_err(errors.STALE_VERSION,
                         "expected_parcel_assessment_version does not match the "
                         "assessment's current version")
    if a["status"] not in _PAYABLE:
        errors.raise_err(errors.ASSESSMENT_NOT_LEVIED,
                         "Assessment is not in a payable status")
    d = STORE.districts[a["district_id"]]
    if a["status"] == "LEVIED" and a["payment_option"] == "PREPAY_FULL":
        if d["payment_option_deadline"] is not None and now() > d["payment_option_deadline"]:
            errors.raise_err(errors.PAYMENT_OPTION_WINDOW_CLOSED,
                             "The payment-option window has closed")
    if amount <= 0:
        errors.raise_err(errors.INVALID_AMOUNT, "amount_cents must be > 0")

    ts = now()
    if a["status"] == "LEVIED":
        # prepay path
        if a["payment_option"] != "PREPAY_FULL":
            errors.raise_err(errors.INVALID_PREPAY_AMOUNT,
                             "Payments on a LEVIED assessment require the PREPAY_FULL option")
        if amount > services.payoff_quote(d, a, ts)["payoff_cents"]:
            errors.raise_err(errors.OVERPAYMENT,
                             "Payment amount exceeds the payoff quote")
        if amount != a["preliminary_amount_cents"]:
            errors.raise_err(errors.INVALID_PREPAY_AMOUNT,
                             "A PREPAY_FULL payment must equal preliminary_amount_cents exactly")
        applied_penalty, applied_interest, applied_principal = 0, 0, amount
        a["total_paid_cents"] += amount
        a["principal_balance_cents"] = a["preliminary_amount_cents"] - amount
        a["status"] = "PREPAID"
    else:
        if amount > services.payoff_quote(d, a, ts)["payoff_cents"]:
            errors.raise_err(errors.OVERPAYMENT,
                             "Payment amount exceeds the payoff quote")
        applied_penalty, applied_interest, applied_principal = \
            services.apply_waterfall(d, a, amount)
        a["total_paid_cents"] += amount

    p = {
        "id": new_id(),
        "parcel_assessment_id": assessment_id,
        "amount_cents": amount,
        "method": method,
        "received_at": ts,
        "applied_penalty_cents": applied_penalty,
        "applied_interest_cents": applied_interest,
        "applied_principal_cents": applied_principal,
        "created_at": ts,
    }
    STORE.put("payments", p)
    touch(a)
    return ok_object(ser_payment(p), 201)


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    p = get_or_404("payments", pid, errors.PAYMENT_NOT_FOUND, "Payment not found")
    return ok_object(ser_payment(p))
