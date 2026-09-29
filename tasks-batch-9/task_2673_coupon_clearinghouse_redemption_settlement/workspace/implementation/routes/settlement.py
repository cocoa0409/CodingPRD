"""Settlement statements and manufacturer invoices (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from services import calc, domain

bp = Blueprint("settlement", __name__)

STATEMENT_ROLES = [
    "Manufacturer",
    "Retailer",
    "SettlementOfficer",
    "FraudAnalyst",
    "ClearinghouseAdmin",
]
INVOICE_ROLES = ["Manufacturer", "SettlementOfficer", "ClearinghouseAdmin"]

STATEMENT_SPEC = {
    "submission_id": {"type": "string", "required": True, "min_len": 1},
    "expected_submission_version": {"type": "integer", "required": True, "min": 0},
    "prior_chargeback_offset_cents": {"type": "integer", "min": 0, "default": 0},
}


# --------------------------------------------------------------- statements
@bp.route("/settlement-statements", methods=["POST"])
def issue_statement():
    ctx = mw.authenticate(["SettlementOfficer"])
    values = validate.parse(mw.body(), STATEMENT_SPEC)
    submission = mw.fetch(
        "submissions", values["submission_id"], "ERR_SUBMISSION_NOT_FOUND"
    )
    if values["expected_submission_version"] != submission["version"]:
        raise ApiError(
            "ERR_STALE_SUBMISSION_VERSION",
            "Submission version is %d" % submission["version"],
        )
    if submission["intake_status"] != "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a CLOSED submission can be settled",
        )
    settleable = [
        l
        for l in domain.lots_of_submission(submission["id"])
        if l["status"] in calc.SETTLEABLE_LOT_STATUSES
    ]
    if not settleable:
        raise ApiError(
            "ERR_EMPTY_SUBMISSION", "Submission has no settleable lots"
        )
    retailer = domain.retailer_of_submission(submission)
    gross = sum(l["gross_face_value_cents"] for l in settleable)
    fee = sum(l["handling_fee_cents"] for l in settleable)
    offset = values["prior_chargeback_offset_cents"]
    provisional = gross + fee - offset
    if provisional < 0:
        validate.fail("prior_chargeback_offset_cents exceeds the settleable amount")
    pct = calc.holdback_pct(provisional, retailer)
    holdback = calc.rhu_int(Decimal(provisional) * pct)
    row = db.base_row()
    row.update(
        {
            "submission_id": submission["id"],
            "retailer_id": retailer["id"],
            "manufacturer_invoice_id": None,
            "prior_chargeback_offset_cents": offset,
            "gross_face_value_cents": gross,
            "handling_fee_total_cents": fee,
            "provisional_net_cents": provisional,
            "holdback_pct": pct,
            "misredemption_holdback_cents": holdback,
            "net_payable_cents": provisional - holdback,
            "scheduled_pay_date": None,
            "status": "DRAFT",
            "hold_reason": None,
            "issued_by_user_id": ctx.user_id,
            "released_by_user_id": None,
        }
    )
    db.db.statements[row["id"]] = row
    touch(submission)
    return response.object_response(row, 201)


@bp.route("/settlement-statements/<stid>", methods=["GET"])
def get_statement(stid):
    ctx = mw.authenticate(STATEMENT_ROLES)
    row = mw.fetch("statements", stid, "ERR_STATEMENT_NOT_FOUND")
    mw.own_retailer(ctx, row["retailer_id"])
    return response.object_response(row)


@bp.route("/settlement-statements", methods=["GET"])
def list_statements():
    mw.authenticate(STATEMENT_ROLES)
    limit, offset = mw.pagination()
    submission_id = mw.str_arg("submission_id")
    retailer_id = mw.str_arg("retailer_id")
    invoice_id = mw.str_arg("manufacturer_invoice_id")
    status = mw.str_arg("status")
    rows = [
        s
        for s in db.db.statements.values()
        if (submission_id is None or s["submission_id"] == submission_id)
        and (retailer_id is None or s["retailer_id"] == retailer_id)
        and (invoice_id is None or s["manufacturer_invoice_id"] == invoice_id)
        and (status is None or s["status"] == status)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/settlement-statements/<stid>/schedule", methods=["POST"])
def schedule_statement(stid):
    mw.authenticate(["SettlementOfficer"])
    statement = mw.fetch("statements", stid, "ERR_STATEMENT_NOT_FOUND")
    validate.require_no_body(mw.body())
    if statement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a DRAFT statement can be scheduled"
        )
    submission = db.db.submissions[statement["submission_id"]]
    if domain.has_open_dispute(submission["id"]):
        raise ApiError("ERR_DISPUTE_OPEN", "An appeal is still live on this submission")
    retailer = db.db.retailers[statement["retailer_id"]]
    pay_date = calc.scheduled_pay_date(db.today(), retailer["payment_terms"])
    statement["scheduled_pay_date"] = db.fmt_date(pay_date)
    statement["status"] = "SCHEDULED"
    touch(statement)
    if submission["settlement_status"] == "PENDING":
        submission["settlement_status"] = "STATEMENT_ISSUED"
        touch(submission)
    domain.recompute_retailer_unpaid(retailer)
    return response.object_response(statement)


@bp.route("/settlement-statements/<stid>/release-payment", methods=["POST"])
def release_payment(stid):
    ctx = mw.authenticate(["SettlementOfficer"])
    statement = mw.fetch("statements", stid, "ERR_STATEMENT_NOT_FOUND")
    validate.require_no_body(mw.body())
    if statement["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SCHEDULED statement can be released",
        )
    if ctx.user_id == statement["issued_by_user_id"]:
        raise ApiError(
            "ERR_SOD_VIOLATION",
            "The officer who issued a statement may not release it",
        )
    invoice = None
    if statement["manufacturer_invoice_id"] is not None:
        invoice = db.db.invoices.get(statement["manufacturer_invoice_id"])
    if invoice is None or invoice["status"] != "FUNDED":
        raise ApiError(
            "ERR_INVOICE_NOT_FUNDED",
            "The statement is not carried by a FUNDED invoice",
        )
    if db.today() < db.parse_date(statement["scheduled_pay_date"]):
        raise ApiError(
            "ERR_PAY_DATE_NOT_REACHED", "The scheduled pay date has not been reached"
        )
    statement["status"] = "PAID"
    statement["released_by_user_id"] = ctx.user_id
    touch(statement)
    submission = db.db.submissions[statement["submission_id"]]
    if submission["settlement_status"] == "STATEMENT_ISSUED":
        submission["settlement_status"] = "PAID"
        submission["hold_reason"] = None
        touch(submission)
    manufacturer = db.db.manufacturers[invoice["manufacturer_id"]]
    domain.recompute_manufacturer_ledger(manufacturer)
    domain.recompute_retailer_unpaid(db.db.retailers[statement["retailer_id"]])
    lines = domain.statements_of_invoice(invoice["id"])
    if lines and all(line["status"] == "PAID" for line in lines):
        invoice["status"] = "RECONCILED"
        touch(invoice)
    return response.object_response(statement)


# ----------------------------------------------------------------- invoices
INVOICE_SPEC = {
    "manufacturer_id": {"type": "string", "required": True, "min_len": 1},
    "billing_period_start": {"type": "date", "required": True},
    "billing_period_end": {"type": "date", "required": True},
    "statement_ids": {
        "type": "array",
        "required": True,
        "max_items": 200,
        "items": {"type": "string", "min_len": 1},
    },
}


@bp.route("/manufacturer-invoices", methods=["POST"])
def create_invoice():
    mw.authenticate(["SettlementOfficer"])
    values = validate.parse(mw.body(), INVOICE_SPEC)
    period_start = db.parse_date(values["billing_period_start"])
    period_end = db.parse_date(values["billing_period_end"])
    if period_start > period_end:
        validate.fail("billing_period_start must not be after billing_period_end")
    manufacturer = mw.fetch(
        "manufacturers", values["manufacturer_id"], "ERR_MANUFACTURER_NOT_FOUND"
    )
    lines = []
    for statement_id in values["statement_ids"]:
        lines.append(mw.fetch("statements", statement_id, "ERR_STATEMENT_NOT_FOUND"))
    if manufacturer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Issuing manufacturer is suspended")
    for statement in lines:
        _require_billable(statement, manufacturer["id"])
    for other in db.db.invoices.values():
        if other["manufacturer_id"] != manufacturer["id"]:
            continue
        if other["status"] == "REVERSED":
            continue
        other_start = db.parse_date(other["billing_period_start"])
        other_end = db.parse_date(other["billing_period_end"])
        gap_after = (period_start - other_end).days
        gap_before = (other_start - period_end).days
        if gap_after <= calc.BILLING_PERIOD_BUFFER_DAYS and \
                gap_before <= calc.BILLING_PERIOD_BUFFER_DAYS:
            raise ApiError(
                "ERR_BILLING_PERIOD_BUFFER_VIOLATION",
                "Billing period must be separated from existing invoices "
                "by at least one clear day",
            )
    if not values["statement_ids"]:
        raise ApiError(
            "ERR_STATEMENT_LINES_EMPTY", "An invoice must name at least one statement"
        )
    if len(set(values["statement_ids"])) != len(values["statement_ids"]):
        raise ApiError(
            "ERR_STATEMENT_LINES_EMPTY", "statement_ids must not repeat an entry"
        )

    billed_face = sum(s["gross_face_value_cents"] for s in lines)
    billed_fee = sum(s["handling_fee_total_cents"] for s in lines)
    clearing = calc.clearing_fee_cents(billed_face)
    total = billed_face + billed_fee + clearing
    row = db.base_row()
    row.update(
        {
            "manufacturer_id": manufacturer["id"],
            "billing_period_start": values["billing_period_start"],
            "billing_period_end": values["billing_period_end"],
            "statement_ids": list(values["statement_ids"]),
            "billed_face_value_cents": billed_face,
            "billed_handling_fee_cents": billed_fee,
            "billed_clearing_fee_cents": clearing,
            "billed_total_cents": total,
            "funded_amount_cents": 0,
            "funding_shortfall_cents": total,
            "status": "ISSUED",
        }
    )
    db.db.invoices[row["id"]] = row
    for statement in lines:
        statement["manufacturer_invoice_id"] = row["id"]
        touch(statement)
    return response.object_response(row, 201)


def _require_billable(statement, manufacturer_id):
    if statement["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError(
            "ERR_STATEMENT_NOT_BILLABLE",
            "Statement in %s cannot be billed" % statement["status"],
        )
    if statement["manufacturer_invoice_id"] is not None:
        raise ApiError(
            "ERR_STATEMENT_NOT_BILLABLE", "Statement is already carried by an invoice"
        )
    settleable = [
        l
        for l in domain.lots_of_submission(statement["submission_id"])
        if l["status"] in calc.SETTLEABLE_LOT_STATUSES
    ]
    for lot in settleable:
        if lot["manufacturer_id"] != manufacturer_id:
            raise ApiError(
                "ERR_STATEMENT_NOT_BILLABLE",
                "Statement covers lots issued by another manufacturer",
            )


@bp.route("/manufacturer-invoices/<invid>", methods=["GET"])
def get_invoice(invid):
    ctx = mw.authenticate(INVOICE_ROLES)
    row = mw.fetch("invoices", invid, "ERR_INVOICE_NOT_FOUND")
    mw.own_manufacturer(ctx, row["manufacturer_id"])
    return response.object_response(row)


@bp.route("/manufacturer-invoices", methods=["GET"])
def list_invoices():
    mw.authenticate(INVOICE_ROLES)
    limit, offset = mw.pagination()
    manufacturer_id = mw.str_arg("manufacturer_id")
    status = mw.str_arg("status")
    rows = [
        i
        for i in db.db.invoices.values()
        if (manufacturer_id is None or i["manufacturer_id"] == manufacturer_id)
        and (status is None or i["status"] == status)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/manufacturer-invoices/<invid>/fund", methods=["POST"])
def fund_invoice(invid):
    ctx = mw.authenticate(["Manufacturer"])
    invoice = mw.fetch("invoices", invid, "ERR_INVOICE_NOT_FOUND")
    mw.own_manufacturer(ctx, invoice["manufacturer_id"])
    values = validate.parse(
        mw.body(), {"amount_cents": {"type": "integer", "required": True, "min": 1}}
    )
    if invoice["status"] not in ("ISSUED", "SHORT_FUNDED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An invoice in %s cannot be funded" % invoice["status"],
        )
    manufacturer = db.db.manufacturers[invoice["manufacturer_id"]]
    if manufacturer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Funding manufacturer is suspended")
    running = invoice["funded_amount_cents"] + values["amount_cents"]
    if running > invoice["billed_total_cents"]:
        raise ApiError(
            "ERR_FUNDING_EXCEEDS_BILLED",
            "Funding would exceed the billed total",
        )
    invoice["funded_amount_cents"] = running
    if running == invoice["billed_total_cents"]:
        was_short = invoice["status"] == "SHORT_FUNDED"
        invoice["funding_shortfall_cents"] = 0
        invoice["status"] = "FUNDED"
        touch(invoice)
        domain.recompute_manufacturer_ledger(manufacturer)
        if was_short:
            domain.release_funding_holds(invoice)
    else:
        invoice["funding_shortfall_cents"] = (
            invoice["billed_total_cents"] - running
        )
        invoice["status"] = "SHORT_FUNDED"
        touch(invoice)
        domain.recompute_manufacturer_ledger(manufacturer)
        domain.apply_funding_shortfall(invoice)
    return response.object_response(invoice)


@bp.route("/manufacturer-invoices/<invid>/reverse-funding", methods=["POST"])
def reverse_funding(invid):
    mw.authenticate(["ClearinghouseAdmin"])
    invoice = mw.fetch("invoices", invid, "ERR_INVOICE_NOT_FOUND")
    validate.parse(
        mw.body(),
        {"reason": {"type": "string", "required": True, "min_len": 1, "max_len": 500}},
    )
    if invoice["status"] not in ("FUNDED", "SHORT_FUNDED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An invoice in %s cannot be reversed" % invoice["status"],
        )
    for statement in domain.statements_of_invoice(invoice["id"]):
        if statement["status"] == "PAID":
            raise ApiError(
                "ERR_STATEMENT_ALREADY_PAID",
                "A statement on this invoice has already been paid",
            )
    invoice["funded_amount_cents"] = 0
    invoice["funding_shortfall_cents"] = invoice["billed_total_cents"]
    invoice["status"] = "REVERSED"
    touch(invoice)
    domain.recompute_manufacturer_ledger(
        db.db.manufacturers[invoice["manufacturer_id"]]
    )
    domain.apply_funding_shortfall(invoice)
    return response.object_response(invoice)
