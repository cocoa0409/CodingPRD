"""Creator funds: allocation, supersession, void and disbursement (PRD 3.9)."""
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

bp = Blueprint("funds", __name__)

READ_ROLES = ("PlatformAdmin", "FinanceOperator", "Auditor", "Creator")
ALLOC_READ_ROLES = ("PlatformAdmin", "FinanceOperator", "Auditor")

CREATE = (
    F("name", "str", required=True, text=(1, 120)),
    F("period_id", "str", required=True),
    F("total_pool_cents", "int", required=True, exclusive_min=0),
    F("methodology", "enum", required=True,
      enum=("PRO_RATA_WATCH_TIME", "GUARANTEED_FLOOR_WATERFALL")),
    F("min_watch_time_minutes", "int", default=0, minv=0),
    F("max_allocation_cents", "int", default=2000000, exclusive_min=0),
)
ALLOCATE = (F("expected_fund_version", "int", required=True),)
VOID = (
    F("expected_fund_version", "int", required=True),
    F("reason", "str", required=True, text=(1, 2000)),
)

PATH = (("fund_id", "funds"),)


def _void_active(fund, reason):
    rows = sort_rows([a for a in db.rows("allocations")
                      if a["fund_id"] == fund["id"] and a["status"] == "ACTIVE"],
                     lambda r: (r["rank"],))
    for row in rows:
        row["status"] = "VOIDED"
        row["voided_at"] = db.now
        row["void_reason"] = reason
        db.touch(row)


@bp.route("/monetization/creator-funds", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), fields=CREATE,
          refs=(("period_id", "periods"),))
def create_fund(ctx):
    period = ctx.refs["period_id"]
    if period["status"] not in ("OPEN", "CLOSED"):                          # 63
        fail("ERR_FUND_PERIOD_FINALIZED", "A FINALIZED period admits no new fund.")
    for other in db.rows("funds"):                                          # 64
        if other["period_id"] == period["id"] and other["status"] in ("DRAFT",
                                                                      "ALLOCATED"):
            fail("ERR_FUND_ALREADY_EXISTS_FOR_PERIOD",
                 "A live fund already exists for this period.")
    if ctx.data["methodology"] == "GUARANTEED_FLOOR_WATERFALL" \
            and ctx.data["max_allocation_cents"] < calc.FUND_GUARANTEED_FLOOR_CENTS:
        fail("ERR_FUND_CAP_BELOW_FLOOR",                                    # 65
             "max_allocation_cents may not sit below the guaranteed floor.")
    row = db.insert("funds", {
        "name": ctx.data["name"],
        "period_id": period["id"],
        "total_pool_cents": ctx.data["total_pool_cents"],
        "methodology": ctx.data["methodology"],
        "min_watch_time_minutes": ctx.data["min_watch_time_minutes"],
        "max_allocation_cents": ctx.data["max_allocation_cents"],
        "status": "DRAFT",
        "allocation_run_count": 0,
        "disbursed_at": None,
    })
    return created(serialize.fund(row))


@bp.route("/monetization/creator-funds", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_funds(ctx):
    rows = filter_rows(db.rows("funds"), request.args, {
        "period_id": "period_id", "status": "status", "methodology": "methodology"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.fund)


@bp.route("/monetization/creator-funds/<fund_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH)
def read_fund(ctx, fund_id):
    return ok(serialize.fund(ctx.path["fund_id"]))


@bp.route("/monetization/creator-funds/<fund_id>/allocate", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH, fields=ALLOCATE)
def allocate_fund(ctx, fund_id):
    fund = ctx.path["fund_id"]
    if fund["status"] not in ("DRAFT", "ALLOCATED"):                        # 40
        fail("ERR_FUND_NOT_ALLOCATABLE", "A DISBURSED fund cannot be re-allocated.")
    if ctx.data["expected_fund_version"] != fund["version"]:                # 42
        fail("ERR_STALE_FUND_VERSION",
             "expected_fund_version does not match the fund's version.")
    candidates = calc.fund_candidates(fund)
    if not candidates:                                                      # 78
        fail("ERR_FUND_POOL_EMPTY", "The candidate pool is empty.")
    if fund["status"] == "ALLOCATED":
        _void_active(fund, "SUPERSEDED_BY_REALLOCATION")
    for creator, rank, amount in calc.fund_allocation(fund, candidates):
        db.insert("allocations", {
            "fund_id": fund["id"],
            "creator_id": creator["id"],
            "amount_cents": amount,
            "rank": rank,
            "methodology_snapshot": fund["methodology"],
            "watch_time_minutes_at_allocation": creator["watch_time_minutes_365d"],
            "status": "ACTIVE",
            "voided_at": None,
            "void_reason": None,
        })
    fund["status"] = "ALLOCATED"
    fund["allocation_run_count"] += 1
    db.touch(fund)
    return ok(serialize.fund(fund))


@bp.route("/monetization/creator-funds/<fund_id>/void-allocations", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH, fields=VOID)
def void_allocations(ctx, fund_id):
    fund = ctx.path["fund_id"]
    if fund["status"] != "ALLOCATED":                                       # 41
        fail("ERR_FUND_NOT_ALLOCATED", "The fund is not ALLOCATED.")
    if ctx.data["expected_fund_version"] != fund["version"]:                # 42
        fail("ERR_STALE_FUND_VERSION",
             "expected_fund_version does not match the fund's version.")
    _void_active(fund, ctx.data["reason"])
    fund["status"] = "DRAFT"
    db.touch(fund)
    return ok(serialize.fund(fund))


@bp.route("/monetization/creator-funds/<fund_id>/disburse", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def disburse_fund(ctx, fund_id):
    fund = ctx.path["fund_id"]
    if fund["status"] != "ALLOCATED":                                       # 41
        fail("ERR_FUND_NOT_ALLOCATED", "The fund is not ALLOCATED.")
    active = sort_rows([a for a in db.rows("allocations")
                        if a["fund_id"] == fund["id"] and a["status"] == "ACTIVE"],
                       lambda r: (r["rank"],))
    if not active:                                                          # 79
        fail("ERR_FUND_NO_RECIPIENTS", "The fund has no active recipients.")
    for row in active:
        creator = db.get("creators", row["creator_id"])
        ledger.append(row["creator_id"], "FUND_CREDIT", row["amount_cents"],
                      "FUND_ALLOCATION", row["id"])
        if creator is not None:
            creator["fund_credit_balance_cents"] += row["amount_cents"]
            db.touch(creator)
    fund["status"] = "DISBURSED"
    fund["disbursed_at"] = db.now
    db.touch(fund)
    return ok(serialize.fund(fund))


@bp.route("/monetization/creator-funds/<fund_id>/fund-allocations", methods=["GET"])
@endpoint(roles=ALLOC_READ_ROLES, path=PATH, listing=True)
def list_fund_allocations(ctx, fund_id):
    rows = [a for a in db.rows("allocations") if a["fund_id"] == fund_id]
    rows = filter_rows(rows, request.args,
                       {"status": "status", "creator_id": "creator_id"})
    rows = sort_rows(rows, lambda r: (r["rank"],))
    return respond(ctx, rows, serialize.allocation)
