"""Earnings statements: finalization, disputes and the compound period state."""
from flask import Blueprint, request

import calc
import ledger
import serialize
from apierrors import fail
from envelope import ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db

bp = Blueprint("statements", __name__)

READ_ROLES = ("Creator", "FinanceOperator", "PlatformAdmin", "Auditor")
FINALIZED_STATUSES = ("FINALIZED", "ADJUSTED", "PAID")

DISPUTE = (
    F("dispute_reason", "str", required=True, text=(1, 2000)),
    F("dispute_claimed_amount_cents", "int", required=True),
)
RESOLVE = (
    F("decision", "enum", required=True, enum=("UPHELD", "REJECTED")),
    F("adjustment_cents", "int", required=True, minv=0),
)

PATH = (("statement_id", "statements"),)
OWN = lambda ctx: ctx.path["statement_id"]["creator_id"]


def refresh_period(period):
    """Compound transition: FINALIZED once every child statement is final."""
    if period is None:
        return
    children = [s for s in db.rows("statements") if s["period_id"] == period["id"]]
    total = len(children)
    final = sum(1 for s in children if s["status"] in FINALIZED_STATUSES)
    if total >= 1 and final == total:
        if period["status"] != "FINALIZED":
            period["status"] = "FINALIZED"
            db.touch(period)


@bp.route("/monetization/earnings-statements", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_statements(ctx):
    rows = db.rows("statements")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id",
        "period_id": "period_id",
        "payout_id": "payout_id",
        "status": "status",
        "withholding_variant": "withholding_variant",
    })
    rows = calc.order_statements(rows)
    return respond(ctx, rows, serialize.statement)


@bp.route("/monetization/earnings-statements/<statement_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_statement(ctx, statement_id):
    return ok(serialize.statement(ctx.path["statement_id"]))


@bp.route("/monetization/earnings-statements/<statement_id>/finalize",
          methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def finalize_statement(ctx, statement_id):
    row = ctx.path["statement_id"]
    if row["status"] != "PROVISIONAL":                                    # 26
        fail("ERR_STATEMENT_NOT_PROVISIONAL", "The statement is not PROVISIONAL.")
    period = db.get("periods", row["period_id"])
    if period is None or period["status"] != "CLOSED":                     # 27
        fail("ERR_PERIOD_NOT_CLOSED", "The statement's period is not CLOSED.")
    provisional = row["withholding_cents"]
    final = calc.statement_withholding(row, "FINAL", period["closed_at"])
    delta = provisional - final
    row["status"] = "FINALIZED"
    row["finalized_at"] = db.now
    db.touch(row)
    if delta != 0:
        ledger.append(row["creator_id"], "WITHHOLDING_TRUE_UP", delta,
                      "EARNINGS_STATEMENT", row["id"])
    refresh_period(period)
    return ok(serialize.statement(row))


@bp.route("/monetization/earnings-statements/<statement_id>/dispute",
          methods=["POST"])
@endpoint(roles=("Creator",), path=PATH, fields=DISPUTE, owner=OWN)
def dispute_statement(ctx, statement_id):
    row = ctx.path["statement_id"]
    if row["status"] not in ("FINALIZED", "ADJUSTED"):                     # 28
        fail("ERR_STATEMENT_NOT_DISPUTABLE", "The statement is not disputable.")
    if row["payout_id"] is not None:                                       # 29
        fail("ERR_STATEMENT_ALREADY_ATTACHED",
             "The statement is already attached to a payout.")
    claimed = ctx.data["dispute_claimed_amount_cents"]
    if claimed <= 0 or claimed > row["net_payable_cents"]:                  # 77
        fail("ERR_DISPUTE_AMOUNT_EXCEEDS_STATEMENT",
             "dispute_claimed_amount_cents is outside (0, net_payable_cents].")
    row["status"] = "UNDER_DISPUTE"
    row["dispute_reason"] = ctx.data["dispute_reason"]
    row["dispute_claimed_amount_cents"] = claimed
    db.touch(row)
    return ok(serialize.statement(row))


@bp.route("/monetization/earnings-statements/<statement_id>/resolve-dispute",
          methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH, fields=RESOLVE)
def resolve_dispute(ctx, statement_id):
    row = ctx.path["statement_id"]
    if row["status"] != "UNDER_DISPUTE":                                   # 30
        fail("ERR_STATEMENT_NOT_UNDER_DISPUTE", "The statement is not disputed.")
    decision = ctx.data["decision"]
    adjustment = ctx.data["adjustment_cents"]
    claimed = row["dispute_claimed_amount_cents"] or 0
    if decision == "REJECTED" and adjustment != 0:                         # 61
        fail("ERR_ADJUSTMENT_OUT_OF_BOUNDS",
             "adjustment_cents must be 0 on a REJECTED resolution.")
    if decision == "UPHELD" and not (0 < adjustment <= claimed):           # 61
        fail("ERR_ADJUSTMENT_OUT_OF_BOUNDS",
             "adjustment_cents must be within (0, dispute_claimed_amount_cents].")
    if decision == "REJECTED":
        row["status"] = "FINALIZED"
        row["dispute_resolution"] = "REJECTED"
        db.touch(row)
    else:
        row["status"] = "ADJUSTED"
        row["dispute_resolution"] = "UPHELD"
        row["dispute_adjustment_cents"] = adjustment
        db.touch(row)
        ledger.append(row["creator_id"], "DISPUTE_ADJUSTMENT", adjustment,
                      "EARNINGS_STATEMENT", row["id"])
    refresh_period(db.get("periods", row["period_id"]))
    return ok(serialize.statement(row))
