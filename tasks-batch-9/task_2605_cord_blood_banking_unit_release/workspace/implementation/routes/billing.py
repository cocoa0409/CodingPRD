"""Storage accounts, invoices and payments (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import endpoint, get_body, v_date, v_int, v_str, v_ts
from response import object_response
from store import base_row, db, iso, pdt, public, touch

bp = Blueprint("billing", __name__)


@bp.route("/cbb/storage-accounts", methods=["POST"])
@endpoint("BillingAdministrator", "PlatformAdmin")
def open_account(user_id, role):
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id", min_len=1)
    email = v_str(body, "billing_contact_email", min_len=1)
    if "@" not in email:
        fail("ERR_VALIDATION_FAILED", "billing_contact_email must contain '@'.")
    term = v_int(body, "plan_term_years", choices=(1, 5, 18))
    prepaid = v_date(body, "prepaid_through_date")

    enrollment = svc.get_enrollment(enrollment_id)
    if enrollment["program_type"] != "PRIVATE_FAMILY":
        fail("ERR_PROGRAM_TYPE_MISMATCH")
    if svc.enrollment_account(enrollment_id) is not None:
        fail("ERR_DUPLICATE_STORAGE_ACCOUNT")

    row = base_row()
    row.update({
        "enrollment_id": enrollment_id,
        "billing_contact_email": email,
        "plan_term_years": term,
        "prepaid_through_date": iso(prepaid),
        "paid_through_date": iso(prepaid),
        "status": "ACTIVE",
        "balance_cents": 0,
        "lifetime_paid_cents": 0,
        "last_settlement_total_cents": None,
        "delinquency_stage_entered_at": None,
    })
    db.accounts[row["id"]] = row
    return object_response(public(row), 201)


@bp.route("/cbb/storage-invoices", methods=["POST"])
@endpoint("BillingAdministrator", "PlatformAdmin")
def issue_invoice(user_id, role):
    body = get_body()
    account_id = v_str(body, "account_id", min_len=1)
    start = v_date(body, "billing_period_start")
    end = v_date(body, "billing_period_end")
    days = v_int(body, "prorated_days", ge=1, le=365)
    if end <= start:
        fail("ERR_VALIDATION_FAILED",
             "billing_period_end must be later than billing_period_start.")

    account = svc.get_account(account_id)
    enrollment = db.enrollments.get(account["enrollment_id"])
    if enrollment is None or enrollment["program_type"] != "PRIVATE_FAMILY":
        fail("ERR_PROGRAM_TYPE_MISMATCH")

    premium = svc.account_premium_tank(account_id)
    base, surcharge, admin = calc.invoice_lines(days, premium)
    row = base_row()
    row.update({
        "account_id": account_id,
        "billing_period_start": iso(start),
        "billing_period_end": iso(end),
        "prorated_days": days,
        "due_date": iso(start + timedelta(days=calc.INVOICE_NET_DAYS)),
        "base_line_cents": base,
        "surcharge_line_cents": surcharge,
        "admin_line_cents": admin,
        "late_fee_line_cents": 0,
        "amount_due_cents": base + surcharge + admin,
        "amount_paid_cents": 0,
        "stage_advanced_at": None,
        "status": "ISSUED",
    })
    db.invoices[row["id"]] = row
    svc.reconcile_balance(account)
    return object_response(public(row), 201)


@bp.route("/cbb/storage-invoices/<iid>/payments", methods=["POST"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def post_payment(user_id, role, iid):
    svc.require_pg_invoice(user_id, role, iid)
    body = get_body()
    amount = v_int(body, "amount_cents", gt=0)
    v_str(body, "payment_reference", min_len=1)
    invoice = svc.get_invoice(iid)

    if invoice["status"] not in svc.OUTSTANDING_INVOICE_STATES:
        fail("ERR_INVALID_INVOICE_STATE")
    residual = invoice["amount_due_cents"] - invoice["amount_paid_cents"]
    if amount > residual:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE")

    account = db.accounts.get(invoice["account_id"])
    invoice["amount_paid_cents"] = invoice["amount_paid_cents"] + amount
    if invoice["amount_paid_cents"] >= invoice["amount_due_cents"]:
        invoice["status"] = "PAID"
    touch(invoice)

    if account is not None:
        account["lifetime_paid_cents"] = account["lifetime_paid_cents"] + amount
        if invoice["status"] == "PAID":
            current = pdt(account["paid_through_date"])
            period_end = pdt(invoice["billing_period_end"])
            if current is None or (period_end is not None and period_end > current):
                account["paid_through_date"] = invoice["billing_period_end"]
        touch(account)
        svc.reconcile_balance(account)
        svc.cure_delinquency(account)
    return object_response(public(invoice))
