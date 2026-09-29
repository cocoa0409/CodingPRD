"""Policy investigations, holds and the retroactive clawback cascade (PRD 3.8)."""
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

bp = Blueprint("investigations", __name__)

READ_ROLES = ("PolicyReviewer", "FinanceOperator", "PlatformAdmin", "Auditor", "Creator")

CREATE = (
    F("creator_id", "str", required=True),
    F("scope", "str", required=True, text=(1, 500)),
    F("violation_window_start", "datetime", required=True),
    F("violation_window_end", "datetime", required=True),
    F("hold_payouts", "bool", default=True),
)
RESOLVE = (F("finding", "str", required=True, text=(1, 2000)),)

PATH = (("investigation_id", "investigations"),)
OWN = lambda ctx: ctx.path["investigation_id"]["creator_id"]


@bp.route("/monetization/investigations", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), fields=CREATE,
          refs=(("creator_id", "creators"),))
def create_investigation(ctx):
    creator = ctx.refs["creator_id"]
    start = ctx.data["violation_window_start"]
    end = ctx.data["violation_window_end"]
    if end < start:                                                        # 69
        fail("ERR_INVESTIGATION_WINDOW_INVALID",
             "violation_window_end must be at or after violation_window_start.")
    for other in db.rows("investigations"):                                # 70
        if other["creator_id"] != creator["id"] or other["state"] != "OPEN":
            continue
        if start <= other["violation_window_end"] and other["violation_window_start"] <= end:
            fail("ERR_INVESTIGATION_WINDOW_OVERLAP",
                 "The window intersects an open investigation of this creator.")
    hold = ctx.data["hold_payouts"]
    hold_amount = max(calc.available_balance_cents(creator), 0) if hold else 0
    row = db.insert("investigations", {
        "creator_id": creator["id"],
        "scope": ctx.data["scope"],
        "violation_window_start": start,
        "violation_window_end": end,
        "hold_payouts": hold,
        "hold_amount_cents": hold_amount,
        "opened_by_user_id": ctx.user_id,
        "state": "OPEN",
        "finding": None,
        "clawback_base_cents": 0,
        "clawback_recovered_cents": 0,
        "clawback_unrecovered_cents": 0,
        "resolved_by_user_id": None,
        "resolved_at": None,
    })
    db.touch(creator)
    calc.apply_payout_state(creator)
    return created(serialize.investigation(row))


@bp.route("/monetization/investigations", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_investigations(ctx):
    rows = db.rows("investigations")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id", "state": "state", "hold_payouts": "hold_payouts"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.investigation)


@bp.route("/monetization/investigations/<investigation_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_investigation(ctx, investigation_id):
    return ok(serialize.investigation(ctx.path["investigation_id"]))


def _guard(ctx, row):
    if row["state"] != "OPEN":                                             # 31
        fail("ERR_INVESTIGATION_NOT_OPEN", "The investigation is not OPEN.")
    if ctx.user_id == row["opened_by_user_id"]:                             # 44
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The opening reviewer may not resolve the investigation.")


@bp.route("/monetization/investigations/<investigation_id>/substantiate",
          methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=RESOLVE)
def substantiate(ctx, investigation_id):
    row = ctx.path["investigation_id"]
    _guard(ctx, row)
    creator = db.get("creators", row["creator_id"])
    row["state"] = "SUBSTANTIATED"                                         # hop 1
    row["resolved_by_user_id"] = ctx.user_id
    row["resolved_at"] = db.now
    row["finding"] = ctx.data["finding"]
    creator["active_strike_count"] += 1
    creator["last_strike_at"] = db.now
    db.touch(creator)
    calc.eligibility_evaluation(creator, db.now)

    swept = sort_rows([e for e in db.rows("revenue_events")
                       if e["creator_id"] == creator["id"]
                       and e["status"] == "ACCRUED"
                       and row["violation_window_start"] <= e["occurred_at"]
                       <= row["violation_window_end"]],
                      lambda r: (r["occurred_at"], r["created_at"]))
    base = 0
    for event in swept:
        base += event["creator_share_cents"]
        event["status"] = "CLAWED_BACK"
        event["last_status_change_at"] = db.now
        db.touch(event)
    row["clawback_base_cents"] = base

    takes, remaining = calc.substantiation_waterfall(creator["id"], base)   # hop 2
    for statement, taken in takes:
        statement["clawback_applied_cents"] += taken
        statement["status"] = "ADJUSTED"
        db.touch(statement)
    row["clawback_recovered_cents"] = base - remaining
    row["clawback_unrecovered_cents"] = remaining
    db.touch(row)
    if row["clawback_recovered_cents"] > 0:                                 # hop 3
        ledger.append(creator["id"], "CLAWBACK", -row["clawback_recovered_cents"],
                      "INVESTIGATION", row["id"])
    if remaining > 0:
        creator["outstanding_clawback_cents"] += remaining
        db.touch(creator)
    calc.apply_payout_state(creator)                                        # hop 4
    if creator["outstanding_clawback_cents"] > 0:                           # hop 5
        _void_pending_payouts(creator)
        calc.apply_payout_state(creator)
    return ok(serialize.investigation(row))


def _void_pending_payouts(creator):
    payouts = sort_rows([p for p in db.rows("payouts")
                         if p["creator_id"] == creator["id"]
                         and p["state"] == "PENDING"],
                        lambda r: (r["created_at"],))
    for payout in payouts:
        payout["state"] = "VOIDED"
        db.touch(payout)
        ledger.append(creator["id"], "PAYOUT_REVERSAL",
                      payout["amount_cents"] + payout["fee_cents"],
                      "PAYOUT", payout["id"])
        for statement in calc.order_statements(
                [s for s in db.rows("statements") if s["payout_id"] == payout["id"]]):
            statement["payout_id"] = None
            db.touch(statement)
        creator["fund_credit_balance_cents"] += payout["fund_credit_cents"]
        db.touch(creator)


@bp.route("/monetization/investigations/<investigation_id>/clear", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=RESOLVE)
def clear_investigation(ctx, investigation_id):
    row = ctx.path["investigation_id"]
    _guard(ctx, row)
    creator = db.get("creators", row["creator_id"])
    row["state"] = "CLEARED"
    row["resolved_by_user_id"] = ctx.user_id
    row["resolved_at"] = db.now
    row["finding"] = ctx.data["finding"]
    db.touch(row)
    db.touch(creator)
    calc.apply_payout_state(creator)
    return ok(serialize.investigation(row))
