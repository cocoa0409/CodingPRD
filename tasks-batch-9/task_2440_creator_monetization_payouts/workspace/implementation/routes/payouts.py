"""Disbursement lifecycle: create, submit, settle, retry (PRD 3.7)."""
from flask import Blueprint, request

import calc
import ledger
import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("payouts", __name__)

READ_ROLES = ("Creator", "FinanceOperator", "PlatformAdmin", "Auditor")

CREATE = (F("creator_id", "str", required=True),)
SETTLE = (
    F("outcome", "enum", required=True, enum=("SUCCEEDED", "FAILED")),
    F("failure_code", "enum",
      enum=("INSUFFICIENT_DETAILS", "BANK_REJECTED", "ACCOUNT_CLOSED")),
)

PATH = (("payout_id", "payouts"),)
OWN = lambda ctx: ctx.path["payout_id"]["creator_id"]


def _attach_statements(creator_id, payout_id):
    rows = [s for s in db.rows("statements")
            if s["creator_id"] == creator_id
            and s["status"] in ("FINALIZED", "ADJUSTED")
            and s["payout_id"] is None]
    for statement in calc.order_statements(rows):
        statement["payout_id"] = payout_id
        db.touch(statement)
    return rows


@bp.route("/monetization/payouts", methods=["POST"])
@endpoint(roles=("Creator", "FinanceOperator"), fields=CREATE,
          refs=(("creator_id", "creators"),),
          owner=lambda ctx: ctx.data.get("creator_id"))
def create_payout(ctx):
    creator = ctx.refs["creator_id"]
    if calc.resolve_payout_state(creator) != "ACCRUING":                   # 37
        fail("ERR_CREATOR_NOT_PAYABLE", "The creator's payout_state is not ACCRUING.")
    profile = calc.current_tax_profile(creator["id"])
    if profile is None or profile["status"] != "VERIFIED":                  # 47
        fail("ERR_TAX_DOCUMENTATION_MISSING", "No VERIFIED tax profile on file.")
    payable = calc.available_balance_cents(creator)
    if payable <= 0:                                                       # 74
        fail("ERR_NO_PAYABLE_BALANCE", "available_balance_cents is not positive.")
    if payable < creator["payout_threshold_cents"]:                        # 75
        fail("ERR_BELOW_PAYOUT_THRESHOLD",
             "available_balance_cents is below payout_threshold_cents.")

    method = creator["payout_method"]
    fee = calc.payout_fee_cents(payable, method)
    fund_credit = min(creator["fund_credit_balance_cents"], payable)
    row = db.insert("payouts", {
        "creator_id": creator["id"],
        "method": method,
        "payable_before_fee_cents": payable,
        "fee_cents": fee,
        "amount_cents": payable - fee,
        "fund_credit_cents": fund_credit,
        "state": "PENDING",
        "failure_code": None,
        "retry_count": 0,
        "submitted_at": None,
        "settled_at": None,
    })
    _attach_statements(creator["id"], row["id"])
    creator["fund_credit_balance_cents"] = 0
    db.touch(creator)
    ledger.append(creator["id"], "PAYOUT_DEBIT", -row["amount_cents"],
                  "PAYOUT", row["id"])
    if fee > 0:
        ledger.append(creator["id"], "PAYOUT_FEE", -fee, "PAYOUT", row["id"])
    calc.apply_payout_state(creator)
    return created(serialize.payout(row))


@bp.route("/monetization/payouts", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_payouts(ctx):
    rows = db.rows("payouts")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id", "state": "state", "method": "method"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.payout)


@bp.route("/monetization/payouts/<payout_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_payout(ctx, payout_id):
    return ok(serialize.payout(ctx.path["payout_id"]))


@bp.route("/monetization/payouts/<payout_id>/submit", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def submit_payout(ctx, payout_id):
    row = ctx.path["payout_id"]
    if row["state"] != "PENDING":                                          # 32
        fail("ERR_PAYOUT_NOT_PENDING", "The payout is not PENDING.")
    creator = db.get("creators", row["creator_id"])
    if calc.resolve_payout_state(creator) == "HOLD":                        # 33
        fail("ERR_PAYOUT_HELD", "The creator's payouts are held.")
    row["state"] = "PROCESSING"
    row["submitted_at"] = db.now
    db.touch(row)
    return ok(serialize.payout(row))


@bp.route("/monetization/payouts/<payout_id>/record-settlement", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH, fields=SETTLE)
def record_settlement(ctx, payout_id):
    row = ctx.path["payout_id"]
    if row["state"] != "PROCESSING":                                       # 34
        fail("ERR_PAYOUT_NOT_PROCESSING", "The payout is not PROCESSING.")
    outcome = ctx.data["outcome"]
    code = ctx.data.get("failure_code")
    if outcome == "FAILED" and code is None:                               # 59
        fail("ERR_FAILURE_CODE_REQUIRED", "failure_code is required on FAILED.")
    if outcome == "SUCCEEDED" and code is not None:                        # 60
        fail("ERR_FAILURE_CODE_FORBIDDEN", "failure_code is forbidden on SUCCEEDED.")
    creator = db.get("creators", row["creator_id"])
    attached = [s for s in db.rows("statements") if s["payout_id"] == row["id"]]
    attached = calc.order_statements(attached)

    if outcome == "SUCCEEDED":
        row["state"] = "PAID"
        row["settled_at"] = db.now
        db.touch(row)
        creator["lifetime_paid_cents"] += row["amount_cents"]
        creator["consecutive_payment_failures"] = 0
        db.touch(creator)
        for statement in attached:
            statement["status"] = "PAID"
            db.touch(statement)
    else:
        terminal = row["retry_count"] >= calc.MAX_PAYOUT_RETRIES
        row["state"] = "ABANDONED" if terminal else "FAILED"
        row["failure_code"] = code
        if terminal:
            row["settled_at"] = db.now
        db.touch(row)
        creator["consecutive_payment_failures"] += 1
        creator["fund_credit_balance_cents"] += row["fund_credit_cents"]
        db.touch(creator)
        ledger.append(creator["id"], "PAYOUT_REVERSAL",
                      row["amount_cents"] + row["fee_cents"], "PAYOUT", row["id"])
        for statement in attached:
            statement["payout_id"] = None
            db.touch(statement)
    calc.apply_payout_state(creator)
    return ok(serialize.payout(row))


@bp.route("/monetization/payouts/<payout_id>/retry", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def retry_payout(ctx, payout_id):
    row = ctx.path["payout_id"]
    if row["state"] != "FAILED":                                           # 35
        fail("ERR_PAYOUT_NOT_FAILED", "The payout is not FAILED.")
    if row["retry_count"] >= calc.MAX_PAYOUT_RETRIES:                      # 36
        fail("ERR_PAYOUT_RETRIES_EXHAUSTED", "The payout has no retries left.")
    creator = db.get("creators", row["creator_id"])
    if calc.available_balance_cents(creator) < row["amount_cents"] + row["fee_cents"]:
        fail("ERR_INSUFFICIENT_BALANCE_FOR_RETRY",                         # 76
             "available_balance_cents no longer covers the payout.")
    row["state"] = "PROCESSING"
    row["retry_count"] += 1
    row["submitted_at"] = db.now
    row["failure_code"] = None
    db.touch(row)
    ledger.append(creator["id"], "PAYOUT_DEBIT", -row["amount_cents"],
                  "PAYOUT", row["id"])
    if row["fee_cents"] > 0:
        ledger.append(creator["id"], "PAYOUT_FEE", -row["fee_cents"],
                      "PAYOUT", row["id"])
    _attach_statements(creator["id"], row["id"])
    consumed = min(creator["fund_credit_balance_cents"], row["fund_credit_cents"])
    if consumed:
        creator["fund_credit_balance_cents"] -= consumed
    db.touch(creator)
    calc.apply_payout_state(creator)
    return ok(serialize.payout(row))
