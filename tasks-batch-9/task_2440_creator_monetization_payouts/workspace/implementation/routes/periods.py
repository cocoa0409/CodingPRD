"""Attribution calendar and the six-step period-close pipeline (PRD 3.5)."""
from flask import Blueprint, request

import calc
import ledger
import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, days, sort_rows

bp = Blueprint("periods", __name__)

ALL_ROLES = ("PlatformAdmin", "FinanceOperator", "Auditor", "Creator", "PolicyReviewer")

CREATE = (
    F("label", "str", required=True, text=(1, 60)),
    F("period_start", "datetime", required=True),
    F("period_end", "datetime", required=True),
)
PATH = (("period_id", "periods"),)


@bp.route("/monetization/earnings-periods", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), fields=CREATE)
def create_period(ctx):
    start, end = ctx.data["period_start"], ctx.data["period_end"]
    if end <= start:                                                      # 66
        fail("ERR_PERIOD_WINDOW_INVALID", "period_end must be after period_start.")
    for other in db.rows("periods"):                                      # 67
        if start < other["period_end"] and other["period_start"] < end:
            fail("ERR_PERIOD_WINDOW_OVERLAP",
                 "The window intersects an existing period.")
    row = db.insert("periods", {
        "label": ctx.data["label"],
        "period_start": start,
        "period_end": end,
        "status": "OPEN",
        "closed_at": None,
    })
    return created(serialize.period(row))


@bp.route("/monetization/earnings-periods", methods=["GET"])
@endpoint(roles=ALL_ROLES, listing=True)
def list_periods(ctx):
    rows = filter_rows(db.rows("periods"), request.args, {"status": "status"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.period)


@bp.route("/monetization/earnings-periods/<period_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES, path=PATH)
def read_period(ctx, period_id):
    return ok(serialize.period(ctx.path["period_id"]))


@bp.route("/monetization/earnings-periods/<period_id>/close", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def close_period(ctx, period_id):
    period = ctx.path["period_id"]
    if period["status"] != "OPEN":                                        # 25
        fail("ERR_PERIOD_NOT_OPEN", "The period is not OPEN.")
    for other in db.rows("periods"):                                      # 68
        if other["id"] != period["id"] and other["status"] == "OPEN" \
                and other["period_start"] < period["period_start"]:
            fail("ERR_PERIOD_CLOSE_OUT_OF_ORDER", "Periods close oldest-first.")

    at = db.now
    _step1_tax_expiry(at)
    _step2_strike_lapse(at)
    creators = sort_rows(db.rows("creators"), lambda r: (r["created_at"],))
    for creator in creators:                                              # step 3
        calc.eligibility_evaluation(creator, at)
    statements = _step4_statements(period, creators)
    _step5_arrears_offset(creators, statements)
    period["status"] = "CLOSED"                                           # step 6
    period["closed_at"] = at
    db.touch(period)
    return ok(serialize.period(period))


def _step1_tax_expiry(at):
    rows = sort_rows([p for p in db.rows("tax_profiles")
                      if p["status"] == "VERIFIED"
                      and p["expires_at"] is not None and p["expires_at"] <= at],
                     lambda r: (r["created_at"],))
    for profile in rows:
        profile["status"] = "EXPIRED"
        profile["withholding_rate_bps"] = calc.BACKUP_WITHHOLDING_BPS
        db.touch(profile)


def _step2_strike_lapse(at):
    rows = sort_rows([c for c in db.rows("creators")
                      if c["active_strike_count"] > 0
                      and c["last_strike_at"] is not None
                      and c["last_strike_at"] + days(calc.STRIKE_ACTIVE_DAYS) <= at],
                     lambda r: (r["created_at"],))
    for creator in rows:
        creator["active_strike_count"] = 0
        db.touch(creator)


def _step4_statements(period, creators):
    made = {}
    for creator in creators:
        events = [e for e in db.rows("revenue_events")
                  if e["period_id"] == period["id"]
                  and e["creator_id"] == creator["id"]
                  and e["status"] == "ACCRUED"]
        if not events:
            continue
        statement = db.insert("statements", {
            "period_id": period["id"],
            "creator_id": creator["id"],
            "payout_id": None,
            "gross_cents": sum(e["gross_amount_cents"] for e in events),
            "creator_share_cents": sum(e["creator_share_cents"] for e in events),
            "event_count": len(events),
            "withholding_variant": "PROVISIONAL",
            "withholding_rate_bps": 0,
            "withholding_cents": 0,
            "net_payable_cents": 0,
            "clawback_applied_cents": 0,
            "dispute_adjustment_cents": 0,
            "status": "PROVISIONAL",
            "finalized_at": None,
            "dispute_reason": None,
            "dispute_claimed_amount_cents": None,
            "dispute_resolution": None,
        })
        withheld = calc.statement_withholding(statement, "PROVISIONAL", None)
        if withheld > 0:
            ledger.append(creator["id"], "WITHHOLDING", -withheld,
                          "EARNINGS_STATEMENT", statement["id"])
        made[creator["id"]] = statement
    return made


def _step5_arrears_offset(creators, statements):
    for creator in creators:
        if creator["outstanding_clawback_cents"] <= 0:
            continue
        statement = statements.get(creator["id"])
        if statement is None:
            continue
        offset = min(creator["outstanding_clawback_cents"],
                     statement["net_payable_cents"])
        if offset <= 0:
            continue
        statement["clawback_applied_cents"] += offset
        db.touch(statement)
        creator["outstanding_clawback_cents"] -= offset
        db.touch(creator)
        ledger.append(creator["id"], "CLAWBACK", -offset,
                      "EARNINGS_STATEMENT", statement["id"])
        calc.apply_payout_state(creator)
