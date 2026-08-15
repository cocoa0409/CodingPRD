"""Payment runs, payments, release gates, and positive-pay acknowledgements."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_VENDOR_BLOCKED,
    ERR_SANCTIONS_REVIEW_PENDING,
    ERR_VENDOR_NOT_ACTIVE,
    ERR_BANK_ACCOUNT_NOT_VERIFIED,
    ERR_BANK_CHANGE_COOLING_OFF,
    ERR_DOCUMENT_EXPIRED,
    ERR_BANK_SNAPSHOT_STALE,
    ERR_DAILY_LIMIT_EXCEEDED,
    ERR_EMPTY_PAYMENT_RUN,
    ERR_SOD_RUN_CREATOR_CANNOT_APPROVE,
    ERR_SOD_RUN_CREATOR_CANNOT_RELEASE,
    ERR_PAYMENT_ALREADY_TERMINAL,
    raise_err,
)
from middleware import (
    require_auth,
    require_role,
    get_body,
    req_str,
    req_enum,
    get_or_404,
    paginate,
    parse_iso_date,
)
from response import ok, ok_list

bp = Blueprint("payments", __name__)


@bp.route("/payment-runs", methods=["POST"])
def create_payment_run():
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst", "TreasuryManager"])
    body = get_body()
    scheduled_date = req_str(body, "scheduled_date")
    parse_iso_date(scheduled_date, "scheduled_date")
    payment_method = req_enum(body, "payment_method", ("CHECK", "ACH", "WIRE"))
    run = db.stamp_new({
        "id": db.new_id(),
        "scheduled_date": scheduled_date,
        "payment_method": payment_method,
        "status": "DRAFT",
        "total_amount_cents": 0,
        "item_count": 0,
        "created_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "released_by_user_id": None,
        "released_at": None,
    })
    db.payment_runs[run["id"]] = run
    return ok(run, status=201)


@bp.route("/payment-runs/<run_id>", methods=["GET"])
def get_payment_run(run_id):
    require_auth()
    return ok(get_or_404(db.payment_runs, run_id, "PaymentRun"))


@bp.route("/payment-runs/<run_id>/invoices", methods=["POST"])
def add_invoice_to_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst"])
    body = get_body()
    invoice_id = req_str(body, "invoice_id")
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    invoice = get_or_404(db.invoices, invoice_id, "Invoice")
    if run["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot accept invoices." % run["status"])
    if invoice["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invoice in status %s cannot be added to a payment run." % invoice["status"])

    # payment-variant screening runs FIRST; its side effects persist even when
    # the add is rejected.
    vendor = db.vendors.get(invoice["vendor_id"])
    check = svc.screen_vendor(vendor, "PAYMENT")
    if check["result"] == "REVIEW":
        svc.suspend_vendor(vendor, ctx, screening_check=check,
                           opened_reason="PAYMENT_SCREENING")
    elif check["result"] == "HIT":
        svc.block_cascade(vendor, ctx)

    # gate order: blocked -> review pending -> not active -> bank -> cooling-off -> W9
    if vendor["status"] == "BLOCKED":
        raise_err(ERR_VENDOR_BLOCKED, "Vendor is BLOCKED.")
    if svc.open_case_for_vendor(vendor["id"]) is not None or check["result"] == "REVIEW":
        raise_err(ERR_SANCTIONS_REVIEW_PENDING,
                  "Vendor has an OPEN sanctions review case or screened REVIEW at payment time.")
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_NOT_ACTIVE,
                  "Vendor in status %s cannot be paid." % vendor["status"])

    primary_id = vendor.get("primary_bank_account_id")
    primary = db.bank_accounts.get(primary_id) if primary_id else None
    if primary is None or primary["status"] != "VERIFIED":
        raise_err(ERR_BANK_ACCOUNT_NOT_VERIFIED,
                  "Vendor has no primary VERIFIED bank account.")
    if db.now() < svc.datetime_from_iso(primary["verified_at"]) + timedelta(hours=svc.BANK_RECENT_HOURS):
        raise_err(ERR_BANK_CHANGE_COOLING_OFF,
                  "Primary bank account was verified less than 72 hours ago.")
    if not svc.vendor_has_live_w9(vendor["id"]):
        raise_err(ERR_DOCUMENT_EXPIRED,
                  "Vendor has no live-valid W9 at payment time.")

    # success: invoice -> IN_PAYMENT_RUN, payment snapshot created
    from datetime import date as _date
    y, m, d = (int(x) for x in run["scheduled_date"].split("-"))
    scheduled = _date(y, m, d)
    discount = svc.compute_discount_cents(invoice, vendor, scheduled)
    fee = svc.WIRE_FEE_CENTS if run["payment_method"] == "WIRE" else 0
    payment = db.stamp_new({
        "id": db.new_id(),
        "payment_run_id": run["id"],
        "invoice_id": invoice["id"],
        "vendor_id": vendor["id"],
        "bank_account_id": primary["id"],
        "bank_account_version": primary["version"],
        "amount_cents": invoice["amount_cents"],
        "discount_applied_cents": discount,
        "fee_cents": fee,
        "net_amount_cents": invoice["amount_cents"] - discount + fee,
        "status": "PENDING",
        "void_reason": None,
    })
    db.payments[payment["id"]] = payment
    check["payment_id"] = payment["id"]
    invoice["status"] = "IN_PAYMENT_RUN"
    db.touch(invoice)
    svc.recompute_run_totals(run)
    db.touch(run)
    return ok(payment, status=201)


@bp.route("/payments/<payment_id>/void", methods=["POST"])
def void_payment(payment_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst"])
    payment = get_or_404(db.payments, payment_id, "Payment")
    if payment["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment in status %s cannot be voided manually." % payment["status"])
    payment["status"] = "VOIDED"
    payment["void_reason"] = "MANUAL_REMOVED"
    db.touch(payment)
    invoice = db.invoices.get(payment["invoice_id"])
    if invoice is not None and invoice["status"] == "IN_PAYMENT_RUN":
        invoice["status"] = "APPROVED"
        db.touch(invoice)
    run = db.payment_runs.get(payment["payment_run_id"])
    if run is not None:
        svc.recompute_run_totals(run)
        if run["status"] == "APPROVED":
            run["status"] = "COMPILED"
            run["approved_by_user_id"] = None
        db.touch(run)
    return ok(payment)


@bp.route("/payment-runs/<run_id>/compile", methods=["POST"])
def compile_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot be compiled." % run["status"])
    svc.recompute_run_totals(run)
    if run["item_count"] < 1:
        raise_err(ERR_EMPTY_PAYMENT_RUN, "Cannot compile a payment run with no payments.")
    run["status"] = "COMPILED"
    db.touch(run)
    return ok(run)


@bp.route("/payment-runs/<run_id>/uncompile", methods=["POST"])
def uncompile_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "COMPILED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot be uncompiled." % run["status"])
    run["status"] = "DRAFT"
    db.touch(run)
    return ok(run)


@bp.route("/payment-runs/<run_id>/approve", methods=["POST"])
def approve_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryManager"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "COMPILED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot be approved." % run["status"])
    if ctx.user_id == run["created_by_user_id"]:
        raise_err(ERR_SOD_RUN_CREATOR_CANNOT_APPROVE,
                  "The run's creator may not approve it (SoD-4a).")
    run["status"] = "APPROVED"
    run["approved_by_user_id"] = ctx.user_id
    db.touch(run)
    return ok(run)


@bp.route("/payment-runs/<run_id>/revoke-approval", methods=["POST"])
def revoke_run_approval(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryManager"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot have its approval revoked." % run["status"])
    run["status"] = "COMPILED"
    run["approved_by_user_id"] = None
    db.touch(run)
    return ok(run)


@bp.route("/payment-runs/<run_id>/release", methods=["POST"])
def release_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryManager"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot be released." % run["status"])
    if ctx.user_id == run["created_by_user_id"]:
        raise_err(ERR_SOD_RUN_CREATOR_CANNOT_RELEASE,
                  "The run's creator may not release it (SoD-4b).")
    # bank snapshot freshness on every non-VOIDED payment
    for p in db.payments.values():
        if p["payment_run_id"] != run["id"] or p["status"] == "VOIDED":
            continue
        vendor = db.vendors.get(p["vendor_id"])
        account = db.bank_accounts.get(p["bank_account_id"])
        if (
            vendor is None
            or vendor.get("primary_bank_account_id") != p["bank_account_id"]
            or account is None
            or account["version"] != p["bank_account_version"]
        ):
            raise_err(ERR_BANK_SNAPSHOT_STALE,
                      "A payment's bank snapshot no longer matches the vendor's current primary.")
    # daily release limit over runs released on the same logical UTC date
    today_s = db.today().isoformat()
    committed = 0
    for other in db.payment_runs.values():
        if other["status"] in ("RELEASED", "CLOSED") and other.get("released_at"):
            if other["released_at"][:10] == today_s:
                committed += other["total_amount_cents"]
    if committed + run["total_amount_cents"] > svc.TREASURY_DAILY_LIMIT_CENTS:
        raise_err(ERR_DAILY_LIMIT_EXCEEDED,
                  "Release would exceed the treasury daily release limit.")
    run["status"] = "RELEASED"
    run["released_by_user_id"] = ctx.user_id
    run["released_at"] = db.fmt_ts(db.now())
    db.touch(run)
    for p in db.payments.values():
        if p["payment_run_id"] == run["id"] and p["status"] == "PENDING":
            p["status"] = "RELEASED"
            db.touch(p)
    return ok(run)


@bp.route("/payment-runs/<run_id>/void", methods=["POST"])
def void_run(run_id):
    ctx = require_auth()
    require_role(ctx, ["TreasuryAnalyst", "TreasuryManager"])
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] not in ("DRAFT", "COMPILED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot be voided." % run["status"])
    for p in db.payments.values():
        if p["payment_run_id"] == run["id"] and p["status"] == "PENDING":
            p["status"] = "VOIDED"
            p["void_reason"] = "RUN_VOIDED"
            db.touch(p)
            invoice = db.invoices.get(p["invoice_id"])
            if invoice is not None and invoice["status"] == "IN_PAYMENT_RUN":
                invoice["status"] = "APPROVED"
                db.touch(invoice)
    run["status"] = "VOIDED"
    svc.recompute_run_totals(run)
    db.touch(run)
    return ok(run)


def _bubble_up(run):
    """Close a RELEASED run once every payment it contains is terminal."""
    if run["status"] != "RELEASED":
        return
    for p in db.payments.values():
        if p["payment_run_id"] == run["id"] and p["status"] not in ("CLEARED", "VOIDED"):
            return
    run["status"] = "CLOSED"
    db.touch(run)


@bp.route("/payment-runs/<run_id>/positive-pay-acks", methods=["POST"])
def positive_pay_acks(run_id):
    ctx = require_auth()
    require_role(ctx, ["BankFileProcessor"])
    body = get_body()
    acks = body.get("acks")
    if not isinstance(acks, list):
        raise_err(ERR_INVALID_REQUEST, "Field 'acks' is required and must be a list.")
    run = get_or_404(db.payment_runs, run_id, "PaymentRun")
    if run["status"] != "RELEASED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Payment run in status %s cannot accept positive-pay acks." % run["status"])

    # pre-validate the whole batch before applying anything
    plan = []
    seen = set()
    for item in acks:
        if not isinstance(item, dict):
            raise_err(ERR_INVALID_REQUEST, "Each ack must be an object.")
        payment_id = item.get("payment_id")
        ack_result = item.get("ack_result")
        if not isinstance(payment_id, str):
            raise_err(ERR_INVALID_REQUEST, "Each ack requires a payment_id string.")
        if ack_result not in ("MATCH", "MISMATCH"):
            raise_err(ERR_INVALID_REQUEST, "ack_result must be one of MATCH, MISMATCH.")
        payment = db.payments.get(payment_id)
        if payment is None or payment["payment_run_id"] != run["id"]:
            raise_err(ERR_NOT_FOUND, "Payment '%s' does not exist in this run." % payment_id)
        if payment["status"] in ("CLEARED", "VOIDED") or payment_id in seen:
            raise_err(ERR_PAYMENT_ALREADY_TERMINAL,
                      "Payment '%s' is already in a terminal state." % payment_id)
        if payment["status"] != "RELEASED":
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Payment in status %s cannot be acknowledged." % payment["status"])
        seen.add(payment_id)
        plan.append((payment, ack_result))

    for payment, ack_result in plan:
        if ack_result == "MATCH":
            payment["status"] = "CLEARED"
            db.touch(payment)
            invoice = db.invoices.get(payment["invoice_id"])
            if invoice is not None and invoice["status"] == "IN_PAYMENT_RUN":
                invoice["status"] = "PAID"
                db.touch(invoice)
            vendor = db.vendors.get(payment["vendor_id"])
            if vendor is not None:
                vendor["last_payment_cleared_at"] = db.fmt_ts(db.now())
                db.touch(vendor)
        else:  # MISMATCH -> ordered fraud chain
            payment["status"] = "VOIDED"
            payment["void_reason"] = "POSITIVE_PAY_MISMATCH"
            db.touch(payment)
            invoice = db.invoices.get(payment["invoice_id"])
            if invoice is not None and invoice["status"] == "IN_PAYMENT_RUN":
                invoice["status"] = "APPROVED"
                db.touch(invoice)
            vendor = db.vendors.get(payment["vendor_id"])
            if vendor is not None:
                svc.suspend_vendor(vendor, ctx, fraud_reason="POSITIVE_PAY_MISMATCH")
        _bubble_up(run)
    return ok(run)


@bp.route("/payment-runs/<run_id>/payments", methods=["GET"])
def list_run_payments(run_id):
    require_auth()
    get_or_404(db.payment_runs, run_id, "PaymentRun")
    items = [p for p in db.payments.values() if p["payment_run_id"] == run_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    require_auth()
    return ok(get_or_404(db.payments, payment_id, "Payment"))


@bp.route("/payments", methods=["GET"])
def list_payments():
    require_auth()
    items = list(db.payments.values())
    for param in ("vendor_id", "invoice_id", "bank_account_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)
