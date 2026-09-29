"""Cost recovery: estimates, deposits, invoices and the ledger (PRD 3.8)."""
from flask import Blueprint

import calc
import services
import validate
from core import must_get, read_endpoint, write_endpoint
from db import store
from errors import fail
from middleware import (
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_REQUESTER,
)
from response import paginate

bp = Blueprint("fees", __name__)

ESTIMATE_FEE_STATES = ("NOT_ASSESSED", "ESTIMATED", "DEPOSIT_DUE")
ADJUDICATED_BASIS_STATES = ("EXEMPTION_REVIEW", "REDACTION", "RELEASE_READY",
                            "PARTIALLY_RELEASED")
INVOICE_FEE_STATES = ("ESTIMATED", "DEPOSIT_DUE", "DEPOSIT_PAID")
INVOICE_PROCESSING_STATES = ("PARTIALLY_RELEASED", "RELEASED", "DENIED")


@bp.route("/records/requests/<request_id>/fee-estimates", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_estimate(ctx, request_id):
    data = validate.body()
    basis = validate.req_enum(data, "basis", calc.ESTIMATE_BASES)
    media_type = validate.req_enum(data, "media_type", calc.MEDIA_TYPES)
    expected_version = validate.req_int(data, "expected_request_version")
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if expected_version != request["version"]:
        fail("ERR_STALE_REQUEST_VERSION",
             "expected_request_version %s does not match %s"
             % (expected_version, request["version"]))
    if request["fee_status"] not in ESTIMATE_FEE_STATES:
        fail("ERR_FEE_STATE_INVALID",
             "an estimate cannot be issued from fee_status %s" % request["fee_status"])
    if basis == "ADJUDICATED" and \
            request["processing_status"] not in ADJUDICATED_BASIS_STATES:
        fail("ERR_ESTIMATE_BASIS_NOT_PERMITTED",
             "an ADJUDICATED estimate requires at least one record ruled responsive")
    requester = store.get("requesters", request["requester_id"])
    figures = calc.fee_estimate_total(request, requester, basis, media_type)
    prior = calc.estimates_of_request(request["id"])
    for estimate in prior:
        if estimate["status"] in ("ACTIVE", "STALE"):
            estimate["status"] = "SUPERSEDED"
    row = store.insert("fee_estimates", {
        "request_id": request["id"],
        "sequence_number": len(prior) + 1,
        "basis": basis,
        "media_type": media_type,
        "status": "ACTIVE",
        "projected_review_minutes": figures["projected_review_minutes"],
        "projected_burden_minutes": figures["projected_burden_minutes"],
        "billable_minutes": figures["billable_minutes"],
        "estimated_labor_cents": figures["estimated_labor_cents"],
        "media_production_cents": figures["media_production_cents"],
        "subtotal_cents": figures["subtotal_cents"],
        "effective_waiver_pct": round(float(figures["effective_waiver_pct"]), 2),
        "waiver_credit_cents": figures["waiver_credit_cents"],
        "estimated_total_cents": figures["estimated_total_cents"],
        "deposit_required_cents": figures["deposit_required_cents"],
    })
    if figures["estimated_total_cents"] == 0:
        request["fee_status"] = "WAIVED"
        services.write_ledger(request["id"], "WAIVER_CREDIT",
                              figures["waiver_credit_cents"],
                              "statutory fee waiver", "WAIVER")
    elif figures["deposit_required_cents"] > 0:
        request["fee_status"] = "DEPOSIT_DUE"
        request["deposit_due_at"] = services.deposit_due_instant()
    else:
        request["fee_status"] = "ESTIMATED"
    services.close_when_fee_settled(request)
    ctx.touch("requests", request["id"])
    return row


@bp.route("/records/requests/<request_id>/payments", methods=["POST"])
@write_endpoint([ROLE_REQUESTER, ROLE_RECORDS_CLERK], code=201)
def post_payment(ctx, request_id):
    data = validate.body()
    # A non-positive amount is ERR_INVALID_AMOUNT, never ERR_VALIDATION.
    amount_cents = validate.req_int(data, "amount_cents")
    memo = validate.opt_str(data, "memo")
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if ctx.role == ROLE_REQUESTER and request["requester_id"] != ctx.user_id:
        fail("ERR_REQUESTER_MISMATCH", "the request belongs to another filer")
    if request["fee_status"] == "WAIVED":
        fail("ERR_FEE_STATE_INVALID", "a waived request takes no payment")
    if amount_cents <= 0:
        fail("ERR_INVALID_AMOUNT", "amount_cents must be strictly greater than zero")
    figures = calc.ledger_figures(request["id"])
    paid = figures["deposit_paid_cents"]
    ceiling = max(request["deposit_required_cents"] - paid,
                  request["invoiced_total_cents"] - paid)
    if amount_cents > ceiling:
        fail("ERR_PAYMENT_EXCEEDS_OUTSTANDING",
             "at most %d cents are currently owed" % max(0, ceiling))
    entry = services.write_ledger(request["id"], "DEPOSIT_PAYMENT", amount_cents,
                                  memo, "DEPOSIT")
    services.settle_after_payment(request)
    return entry


@bp.route("/records/requests/<request_id>/invoice", methods=["POST"])
@write_endpoint([ROLE_RECORDS_SUPERVISOR], code=200)
def issue_invoice(ctx, request_id):
    data = validate.body()
    memo = validate.opt_str(data, "memo")
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if request["fee_status"] not in INVOICE_FEE_STATES:
        fail("ERR_FEE_STATE_INVALID",
             "an invoice cannot be issued from fee_status %s" % request["fee_status"])
    if request["processing_status"] not in INVOICE_PROCESSING_STATES:
        fail("ERR_REQUEST_NOT_RELEASE_READY",
             "invoicing requires the request to be released, partially released "
             "or denied")
    requester = store.get("requesters", request["requester_id"])
    figures = calc.fee_invoice_total(request, requester)
    request["invoiced_total_cents"] = figures["invoiced_total_cents"]
    labor_component = figures["labor_cents"] + figures["review_cents"]
    services.write_ledger(request["id"], "LABOR_CHARGE", -labor_component,
                          memo, "INVOICE")
    services.write_ledger(request["id"], "MEDIA_CHARGE", -figures["media_cents"],
                          memo, "INVOICE")
    services.write_ledger(request["id"], "WAIVER_CREDIT",
                          figures["waiver_credit_cents"], memo, "INVOICE")
    ledger = calc.ledger_figures(request["id"])
    if ledger["deposit_paid_cents"] >= figures["invoiced_total_cents"]:
        request["fee_status"] = "SETTLED"
    else:
        request["fee_status"] = "INVOICED"
    services.close_when_fee_settled(request)
    return request


@bp.route("/records/fee-ledger-entries/<entry_id>/reversal", methods=["POST"])
@write_endpoint([ROLE_RECORDS_SUPERVISOR], code=201)
def reverse_entry(ctx, entry_id):
    data = validate.body()
    memo = validate.req_str(data, "memo")
    target = must_get("fee_ledger_entries", entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")
    if target["entry_type"] == "REVERSAL":
        fail("ERR_ENTRY_ALREADY_REVERSED", "a reversal cannot itself be reversed")
    for entry in store.all("fee_ledger_entries"):
        if entry.get("reverses_entry_id") == target["id"]:
            fail("ERR_ENTRY_ALREADY_REVERSED",
                 "the entry has already been reversed")
    reversal = services.write_ledger(target["request_id"], "REVERSAL",
                                     -target["amount_cents"], memo, "ADJUSTMENT",
                                     reverses_entry_id=target["id"])
    request = store.get("requests", target["request_id"])
    if request is not None and request["fee_status"] == "SETTLED":
        ledger = calc.ledger_figures(request["id"])
        if ledger["deposit_paid_cents"] < request["invoiced_total_cents"] or \
                ledger["deposit_balance_cents"] < 0:
            request["fee_status"] = "INVOICED"
    return reversal


# -- reads -----------------------------------------------------------------
@bp.route("/records/fee-ledger-entries/<entry_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR])
def get_entry(ctx, entry_id):
    return must_get("fee_ledger_entries", entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


@bp.route("/records/fee-ledger-entries", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR])
def list_entries(ctx):
    limit, offset = validate.pagination()
    request_id = validate.query_str("request_id")
    reverses_entry_id = validate.query_str("reverses_entry_id")
    entry_type = validate.query_enum("entry_type", calc.ENTRY_TYPES)
    rows = store.all("fee_ledger_entries")
    if request_id is not None:
        rows = [row for row in rows if row["request_id"] == request_id]
    if reverses_entry_id is not None:
        rows = [row for row in rows
                if row.get("reverses_entry_id") == reverses_entry_id]
    if entry_type is not None:
        rows = [row for row in rows if row["entry_type"] == entry_type]
    return paginate(rows, limit, offset)


@bp.route("/records/requests/<request_id>/fee-estimates", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_REQUESTER])
def list_estimates(ctx, request_id):
    limit, offset = validate.pagination()
    status = validate.query_enum("status", calc.ESTIMATE_STATUSES)
    must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    rows = calc.estimates_of_request(request_id)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows = sorted(rows, key=lambda row: row["sequence_number"])
    return paginate(rows, limit, offset)
