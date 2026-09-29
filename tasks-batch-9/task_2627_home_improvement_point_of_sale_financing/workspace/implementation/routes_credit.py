"""Consumers, the point-of-sale application, disclosure, origination, payments."""
from datetime import timedelta

from flask import Blueprint

import calc
import ops
import serialize as ser
import validate as v
from errors import fail
from response import created, listing, ok
from store import db
from util import fmt_date, fmt_dt

bp = Blueprint("credit", __name__)

ALL_READ_ROLES = ("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                  "ServicingAgent", "Merchant", "Consumer")
OPERATOR_READ_ROLES = ("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                       "ServicingAgent", "Merchant")


# =============================================================================
# Consumers (PRD 3.4)
# =============================================================================
@bp.post("/consumers")
def register_consumer():
    roles = ("Merchant", "ProgramAdmin")
    ctx = v.authorize(roles)
    body = v.read_body(ctx)
    full_name = v.req_str(body, "full_name")
    ssn_last4 = v.req_str(body, "ssn_last4")
    annual_income = v.req_money(body, "annual_income_cents", positive=True)
    fico_score = v.req_int(body, "fico_score", minimum=300, maximum=850)
    state_code = v.req_str(body, "state_code")
    v.resolve_identity(ctx, roles)
    rec = db.new_record()
    rec.update({
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "annual_income_cents": annual_income,
        "fico_score": fico_score,
        "state_code": state_code,
    })
    db.consumers[rec["id"]] = rec
    return created(ser.consumer(rec))


@bp.get("/consumers/<consumer_id>")
def read_consumer(consumer_id):
    ctx = v.authorize(ALL_READ_ROLES)
    rec = v.get_consumer(consumer_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.consumer_scope(ctx, consumer_id)
    return ok(ser.consumer(rec))


# =============================================================================
# Point-of-sale credit applications (PRD 3.4)
# =============================================================================
@bp.post("/credit-applications")
def create_application():
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    consumer_id = v.req_str(body, "consumer_id")
    merchant_id = v.req_str(body, "merchant_id")
    plan_id = v.req_str(body, "promotion_plan_id")
    project_amount = v.req_money(body, "project_amount_cents", positive=True)
    # Band 6 — body foreign keys in payload-declaration order, trade rule last.
    consumer = v.get_consumer(consumer_id)
    merchant = v.get_merchant(merchant_id)
    plan = v.get_plan(plan_id)
    rule = v.get_trade_rule(merchant["trade_type"])
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, merchant_id)
    # Band 14
    if merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may sell at the point of sale.")
    # Band 31 — the promotion gate, then the live-licence gate.
    today = db.today()
    enrolled = False
    for enrollment in db.ordered(db.enrollments):
        if (enrollment["merchant_id"] == merchant_id
                and enrollment["promotion_plan_id"] == plan_id
                and enrollment["status"] == "ACTIVE"
                and calc.parse_date(enrollment["window_start_date"]) <= today
                <= calc.parse_date(enrollment["window_end_date"])):
            enrolled = True
            break
    if not enrolled:
        fail("ERR_PROMOTION_NOT_ENROLLED",
             "This merchant holds no active enrollment in plan %s today." % plan["code"])
    live_license = any(
        lic["merchant_id"] == merchant_id
        and lic["verification_status"] == "VERIFIED"
        and lic["trade_type"] == merchant["trade_type"]
        and lic["state_code"] == merchant["state_code"]
        for lic in db.licenses.values())
    if not live_license:
        fail("ERR_LICENSE_EXPIRED",
             "This merchant holds no verified licence for its trade and state.")
    # Band 46 / 47
    if project_amount < plan["min_ticket_cents"]:
        fail("ERR_TICKET_BELOW_MINIMUM",
             "The ticket is below the plan's minimum.")
    ticket_ceiling = min(plan["max_ticket_cents"], rule["max_ticket_cents"])
    if project_amount > ticket_ceiling:
        fail("ERR_TICKET_LIMIT_EXCEEDED",
             "The ticket exceeds the lower of the plan and trade ceilings.")
    decision, approved_limit, decision_dti, reasons = calc.instant_credit_decision(
        consumer, project_amount)
    rec = db.new_record()
    rec.update({
        "merchant_id": merchant_id,
        "consumer_id": consumer_id,
        "promotion_plan_id": plan_id,
        "project_amount_cents": project_amount,
        "decision": decision,
        "approved_limit_cents": approved_limit,
        "decision_dti_bps": decision_dti,
        "decision_reason_codes": reasons,
        "disclosure_status": "NOT_SENT",
        "disclosure_template_version": None,
        "disclosure_delivered_at": None,
        "disclosure_acknowledged_at": None,
        "consumer_signature_ref": None,
        "offer_expires_at": db.now() + timedelta(days=calc.OFFER_VALIDITY_DAYS),
        "promo_disclosure_summary": None,
    })
    db.applications[rec["id"]] = rec
    return created(ser.application(rec))


@bp.get("/credit-applications/<application_id>")
def read_application(application_id):
    ctx = v.authorize(ALL_READ_ROLES)
    rec = v.get_application(application_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, rec["merchant_id"])
    v.consumer_scope(ctx, rec["consumer_id"])
    return ok(ser.application(rec))


@bp.get("/credit-applications")
def list_applications():
    ctx = v.authorize(OPERATOR_READ_ROLES)
    v.resolve_identity(ctx, OPERATOR_READ_ROLES)
    limit, offset = v.pagination()
    merchant_id = v.filter_arg("merchant_id")
    consumer_id = v.filter_arg("consumer_id")
    plan_id = v.filter_arg("promotion_plan_id")
    decision = v.filter_arg("decision")
    disclosure_status = v.filter_arg("disclosure_status")
    rows = []
    for rec in db.ordered(db.applications):
        if ctx.role == "Merchant" and rec["merchant_id"] != ctx.user_id:
            continue
        if merchant_id is not None and rec["merchant_id"] != merchant_id:
            continue
        if consumer_id is not None and rec["consumer_id"] != consumer_id:
            continue
        if plan_id is not None and rec["promotion_plan_id"] != plan_id:
            continue
        if decision is not None and rec["decision"] != decision:
            continue
        if disclosure_status is not None and rec["disclosure_status"] != disclosure_status:
            continue
        rows.append(rec)
    page = v.paginate(rows, limit, offset)
    return listing([ser.application(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Disclosure delivery, acknowledgement and acceptance (PRD 3.5)
# =============================================================================
@bp.post("/credit-applications/<application_id>/disclosure-delivery")
def deliver_disclosure(application_id):
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    template_version = v.req_str(body, "disclosure_template_version")
    app = v.get_application(application_id)
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, app["merchant_id"])
    # Band 16 — the disclosure dimension, then the decision dimension.
    if app["disclosure_status"] not in ("NOT_SENT", "EXPIRED_UNACKNOWLEDGED"):
        fail("ERR_INVALID_APPLICATION_STATE",
             "A disclosure standing at %s may not be delivered."
             % app["disclosure_status"])
    if app["decision"] not in ("APPROVED", "COUNTER_OFFERED"):
        fail("ERR_INVALID_APPLICATION_STATE",
             "An application in %s carries no live offer to disclose." % app["decision"])
    plan = db.promotion_plans.get(app["promotion_plan_id"])
    # Band 26
    if plan is None or template_version != plan["disclosure_template_version"]:
        fail("ERR_DISCLOSURE_TEMPLATE_MISMATCH",
             "The supplied template version is not the plan's current version.")
    delivered_at = db.now()
    expiration_date = calc.promo_expiry_date(delivered_at.date(),
                                             plan["promo_term_months"])
    app["disclosure_status"] = "DELIVERED"
    app["disclosure_template_version"] = template_version
    app["disclosure_delivered_at"] = delivered_at
    app["disclosure_acknowledged_at"] = None
    app["promo_disclosure_summary"] = {
        "promo_term_months": plan["promo_term_months"],
        "deferred_apr_bps": plan["deferred_apr_bps"],
        "post_promo_apr_bps": plan["post_promo_apr_bps"],
        "expiration_date": fmt_date(expiration_date),
        "interest_at_risk_note": (
            "Deferred interest accrues at %d basis points from the first advance and "
            "becomes payable in full if the balance is not paid by %s."
            % (plan["deferred_apr_bps"], fmt_date(expiration_date))),
    }
    ops.bump(app)
    return ok(ser.application(app))


@bp.post("/credit-applications/<application_id>/disclosure-acknowledgement")
def acknowledge_disclosure(application_id):
    ctx = v.authorize(("Consumer",))
    body = v.read_body(ctx)
    signature_ref = v.req_str(body, "consumer_signature_ref")
    acknowledged_version = v.opt_str(body, "acknowledged_template_version")
    app = v.get_application(application_id)
    v.resolve_identity(ctx, ("Consumer",))
    v.consumer_scope(ctx, app["consumer_id"])
    # Band 16
    if app["disclosure_status"] != "DELIVERED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "A disclosure standing at %s may not be acknowledged."
             % app["disclosure_status"])
    # Band 27 — the three-day boundary is inclusive.
    deadline = app["disclosure_delivered_at"] + timedelta(days=calc.DISCLOSURE_ACK_DAYS)
    if db.now() > deadline:
        fail("ERR_DISCLOSURE_WINDOW_EXPIRED",
             "The three-day acknowledgement window has closed.")
    if (acknowledged_version is not None
            and acknowledged_version != app["disclosure_template_version"]):
        fail("ERR_DISCLOSURE_TEMPLATE_MISMATCH",
             "The acknowledged template version does not match the delivered one.")
    app["disclosure_status"] = "ACKNOWLEDGED"
    app["disclosure_acknowledged_at"] = db.now()
    app["consumer_signature_ref"] = signature_ref
    ops.bump(app)
    return ok(ser.application(app))


@bp.post("/credit-applications/<application_id>/acceptance")
def accept_offer(application_id):
    ctx = v.authorize(("Consumer",))
    body = v.read_body(ctx)
    accept_counter_offer = v.opt_bool(body, "accept_counter_offer")
    app = v.get_application(application_id)
    v.resolve_identity(ctx, ("Consumer",))
    v.consumer_scope(ctx, app["consumer_id"])
    # Band 16 — decision admission, then the counter-offer flag.
    if app["decision"] not in ("APPROVED", "COUNTER_OFFERED"):
        fail("ERR_INVALID_APPLICATION_STATE",
             "An application in %s may not be accepted." % app["decision"])
    if app["decision"] == "COUNTER_OFFERED" and accept_counter_offer is not True:
        fail("ERR_COUNTER_OFFER_NOT_ACCEPTED",
             "A counter-offered application requires accept_counter_offer = true.")
    # Band 28
    if app["disclosure_status"] != "ACKNOWLEDGED":
        fail("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
             "The deferred-interest disclosure has not been acknowledged.")
    # Band 44 — the boundary is inclusive.
    if app["offer_expires_at"] is not None and db.now() > app["offer_expires_at"]:
        fail("ERR_OFFER_EXPIRED", "The offer lapsed at %s."
             % fmt_dt(app["offer_expires_at"]))
    merchant = db.merchants.get(app["merchant_id"])
    if merchant is None or merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "The selling merchant is no longer approved.")
    consumer = v.get_consumer(app["consumer_id"])
    # Band 48 — a breach revokes the offer rather than activating it.
    debt = calc.existing_program_debt_cents(consumer["id"])
    ratio = calc.dti_bps(debt, app["project_amount_cents"],
                         consumer["annual_income_cents"])
    if ratio > calc.DTI_CEILING_BPS:
        app["decision"] = "REVOKED"
        app["decision_reason_codes"] = list(app["decision_reason_codes"]) + [
            "REVOKED_DTI_BREACH"]
        ops.bump(app)
        fail("ERR_DTI_LIMIT_EXCEEDED",
             "The recomputed debt-to-income ratio of %d basis points exceeds the ceiling."
             % ratio)
    plan = v.get_plan(app["promotion_plan_id"])
    acceptance_date = db.today()
    acct = db.new_record()
    acct.update({
        "application_id": app["id"],
        "consumer_id": app["consumer_id"],
        "merchant_id": app["merchant_id"],
        "promotion_plan_id": app["promotion_plan_id"],
        "credit_limit_cents": app["approved_limit_cents"],
        "capitalized_interest_cents": 0,
        "waived_interest_cents": 0,
        "promo_status": "PROMO_ACTIVE",
        "balance_status": "CURRENT",
        "promo_expires_on": fmt_date(calc.promo_expiry_date(
            acceptance_date, plan["promo_term_months"])),
        "apr_bps": plan["deferred_apr_bps"],
        "first_funding_on": None,
        "last_payment_on": None,
    })
    db.loan_accounts[acct["id"]] = acct
    app["decision"] = "ACTIVATED"
    ops.bump(app)
    ops.bump(consumer)
    return ok(ser.application(app))


# =============================================================================
# Loan accounts (PRD 3.5, 3.9)
# =============================================================================
@bp.get("/loan-accounts/<account_id>")
def read_loan_account(account_id):
    ctx = v.authorize(ALL_READ_ROLES)
    acct = v.get_loan_account(account_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, acct["merchant_id"])
    v.consumer_scope(ctx, acct["consumer_id"])
    return ok(ser.loan_account(acct))


@bp.get("/loan-accounts")
def list_loan_accounts():
    ctx = v.authorize(ALL_READ_ROLES)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    limit, offset = v.pagination()
    application_id = v.filter_arg("application_id")
    consumer_id = v.filter_arg("consumer_id")
    merchant_id = v.filter_arg("merchant_id")
    plan_id = v.filter_arg("promotion_plan_id")
    promo_status = v.filter_arg("promo_status")
    balance_status = v.filter_arg("balance_status")
    rows = []
    for acct in db.ordered(db.loan_accounts):
        if ctx.role == "Merchant" and acct["merchant_id"] != ctx.user_id:
            continue
        if ctx.role == "Consumer" and acct["consumer_id"] != ctx.user_id:
            continue
        if application_id is not None and acct["application_id"] != application_id:
            continue
        if consumer_id is not None and acct["consumer_id"] != consumer_id:
            continue
        if merchant_id is not None and acct["merchant_id"] != merchant_id:
            continue
        if plan_id is not None and acct["promotion_plan_id"] != plan_id:
            continue
        if promo_status is not None and acct["promo_status"] != promo_status:
            continue
        if balance_status is not None and acct["balance_status"] != balance_status:
            continue
        rows.append(acct)
    page = v.paginate(rows, limit, offset)
    return listing([ser.loan_account(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Payments (PRD 3.9)
# =============================================================================
@bp.post("/payments")
def post_payment():
    roles = ("Consumer", "ServicingAgent")
    ctx = v.authorize(roles)
    body = v.read_body(ctx)
    account_id = v.req_str(body, "loan_account_id")
    amount = v.req_money(body, "amount_cents", positive=True)
    acct = v.get_loan_account(account_id)
    v.resolve_identity(ctx, roles)
    v.consumer_scope(ctx, acct["consumer_id"])
    # Band 23
    if acct["balance_status"] in ("PAID_OFF", "CHARGED_OFF"):
        fail("ERR_LOAN_CLOSED", "The account is closed to further money movement.")
    pre_principal = calc.principal_balance_cents(acct)
    pre_capitalized = acct["capitalized_interest_cents"]
    # Band 54
    if amount > pre_principal + pre_capitalized:
        fail("ERR_PAYMENT_EXCEEDS_PAYOFF",
             "The payment exceeds the account's payoff amount.")
    cure_threshold = calc.cure_threshold_cents(acct)
    to_interest = min(amount, pre_capitalized)
    to_principal = amount - to_interest
    payment = db.new_record(versioned=False)
    payment.update({
        "loan_account_id": acct["id"],
        "amount_cents": amount,
        "posted_on": fmt_date(db.today()),
        "applied_to_capitalized_interest_cents": to_interest,
        "applied_to_principal_cents": to_principal,
        "resulting_principal_balance_cents": pre_principal - to_principal,
        "source_role": "CONSUMER" if ctx.role == "Consumer" else "SERVICING_AGENT",
    })
    db.payments[payment["id"]] = payment
    acct["capitalized_interest_cents"] = pre_capitalized - to_interest
    acct["last_payment_on"] = payment["posted_on"]
    ops.bump(acct)
    consumer = db.consumers.get(acct["consumer_id"])
    if consumer is not None:
        ops.bump(consumer)
    new_principal = calc.principal_balance_cents(acct)
    merchant = db.merchants.get(acct["merchant_id"])
    # A delinquent account is cured by a payment of at least 500 bps of the debt.
    if acct["balance_status"] == "DELINQUENT" and amount >= cure_threshold:
        acct["balance_status"] = "CURRENT"
        if merchant is not None:
            ops.bump(merchant)
    # The promotional wager: principal cleared on or before the inclusive last day.
    if (acct["promo_status"] == "PROMO_ACTIVE" and new_principal <= 0
            and acct["promo_expires_on"]
            and db.today() <= calc.parse_date(acct["promo_expires_on"])):
        acct["waived_interest_cents"] = calc.accrued_deferred_interest_cents(acct)
        acct["promo_status"] = "PROMO_SATISFIED"
        if acct["balance_status"] == "CURRENT":
            acct["balance_status"] = "PAID_OFF"
    # Otherwise a full payoff of both buckets closes the repayment dimension.
    if (new_principal <= 0 and acct["capitalized_interest_cents"] <= 0
            and acct["balance_status"] == "CURRENT"):
        acct["balance_status"] = "PAID_OFF"
    return created(ser.payment(payment))


@bp.get("/loan-accounts/<account_id>/payments")
def list_payments(account_id):
    ctx = v.authorize(ALL_READ_ROLES)
    acct = v.get_loan_account(account_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, acct["merchant_id"])
    v.consumer_scope(ctx, acct["consumer_id"])
    limit, offset = v.pagination()
    rows = sorted(calc.account_payments(account_id),
                  key=lambda p: (p["posted_on"], p["_seq"]))
    page = v.paginate(rows, limit, offset)
    return listing([ser.payment(r) for r in page], limit, offset, len(rows))
