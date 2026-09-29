"""Creator registration, metrics, eligibility, strikes and creator-scoped reads."""
from flask import Blueprint, request

import calc
import serialize
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("creators", __name__)

COUNTRIES = ("US", "GB", "DE", "IN", "BR", "JP")
METHODS = ("BANK_TRANSFER", "INSTANT_DEBIT", "CHECK")
ALL_ROLES = ("PlatformAdmin", "FinanceOperator", "PolicyReviewer", "Auditor", "Creator")
READ_ROLES = ("Creator", "FinanceOperator", "PlatformAdmin", "Auditor")

CREATE = (
    F("display_name", "str", required=True, text=(1, 120)),
    F("country_code", "enum", required=True, enum=COUNTRIES),
    F("follower_count", "int", required=True, minv=0),
    F("watch_time_minutes_365d", "int", required=True, minv=0),
    F("payout_threshold_cents", "int", default=10000, minv=1000),
    F("payout_method", "enum", default="BANK_TRANSFER", enum=METHODS),
)
METRICS = (
    F("follower_count", "int", minv=0),
    F("watch_time_minutes_365d", "int", minv=0),
)
SETTINGS = (
    F("payout_method", "enum", enum=METHODS),
    F("payout_threshold_cents", "int", minv=1000),
)
STRIKE = (F("reason", "str", required=True, text=(1, 2000)),)

PATH = (("creator_id", "creators"),)
OWN = lambda ctx: ctx.path["creator_id"]["id"]


@bp.route("/monetization/creators", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), fields=CREATE)
def create_creator(ctx):
    row = db.insert("creators", {
        "display_name": ctx.data["display_name"],
        "country_code": ctx.data["country_code"],
        "follower_count": ctx.data["follower_count"],
        "watch_time_minutes_365d": ctx.data["watch_time_minutes_365d"],
        "active_strike_count": 0,
        "last_strike_at": None,
        "eligibility_status": "PENDING_REVIEW",
        "payout_state": "ACCRUING",
        "payout_threshold_cents": ctx.data["payout_threshold_cents"],
        "payout_method": ctx.data["payout_method"],
        "consecutive_payment_failures": 0,
        "fund_credit_balance_cents": 0,
        "outstanding_clawback_cents": 0,
        "lifetime_paid_cents": 0,
        "evaluation_count": 0,
        "last_evaluated_at": None,
        "last_evaluation_failed_criteria": [],
    })
    return created(serialize.creator(row))


@bp.route("/monetization/creators", methods=["GET"])
@endpoint(roles=ALL_ROLES, listing=True)
def list_creators(ctx):
    rows = db.rows("creators")
    if ctx.is_creator:
        rows = [r for r in rows if r["id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "eligibility_status": "eligibility_status",
        "payout_state": "payout_state",
        "country_code": "country_code",
    })
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.creator)


@bp.route("/monetization/creators/<creator_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES, path=PATH, owner=OWN)
def read_creator(ctx, creator_id):
    return ok(serialize.creator(ctx.path["creator_id"]))


@bp.route("/monetization/creators/<creator_id>/metrics", methods=["PATCH"])
@endpoint(roles=("PlatformAdmin",), path=PATH, fields=METRICS)
def patch_metrics(ctx, creator_id):
    row = ctx.path["creator_id"]
    for name in ("follower_count", "watch_time_minutes_365d"):
        if name in ctx.data and ctx.data[name] is not None:
            row[name] = ctx.data[name]
    db.touch(row)
    return ok(serialize.creator(row))


@bp.route("/monetization/creators/<creator_id>/evaluate", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH)
def evaluate_creator(ctx, creator_id):
    row = ctx.path["creator_id"]
    calc.eligibility_evaluation(row, db.now)
    return ok(serialize.creator(row))


@bp.route("/monetization/creators/<creator_id>/policy-strikes", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=STRIKE)
def add_strike(ctx, creator_id):
    row = ctx.path["creator_id"]
    row["active_strike_count"] += 1                                    # hop 1
    row["last_strike_at"] = db.now
    db.touch(row)
    calc.eligibility_evaluation(row, db.now)                           # hop 2
    return ok(serialize.creator(row))


@bp.route("/monetization/creators/<creator_id>/payout-settings", methods=["POST"])
@endpoint(roles=("Creator", "FinanceOperator"), path=PATH, fields=SETTINGS, owner=OWN)
def payout_settings(ctx, creator_id):
    row = ctx.path["creator_id"]
    method = ctx.data.get("payout_method")
    if method is not None and method != row["payout_method"]:
        row["payout_method"] = method
        row["consecutive_payment_failures"] = 0
    threshold = ctx.data.get("payout_threshold_cents")
    if threshold is not None:
        row["payout_threshold_cents"] = threshold
    db.touch(row)
    return ok(serialize.creator(row))


@bp.route("/monetization/creators/<creator_id>/ledger-entries", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN, listing=True)
def list_ledger(ctx, creator_id):
    rows = [e for e in db.rows("ledger") if e["creator_id"] == creator_id]
    rows = filter_rows(rows, request.args, {
        "entry_type": "entry_type",
        "source_entity": "source_entity",
        "source_id": "source_id",
    })
    rows = sort_rows(rows, lambda r: (r["occurred_at"], r["created_at"]))
    return respond(ctx, rows, serialize.ledger_entry)


@bp.route("/monetization/creators/<creator_id>/fund-allocations", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN, listing=True)
def list_creator_allocations(ctx, creator_id):
    rows = [a for a in db.rows("allocations") if a["creator_id"] == creator_id]
    rows = filter_rows(rows, request.args, {"status": "status", "fund_id": "fund_id"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.allocation)


@bp.route("/monetization/creators/<creator_id>/earnings-summary", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def earnings_summary(ctx, creator_id):
    row = ctx.path["creator_id"]
    calc.apply_payout_state(row)
    return ok(serialize.creator(row))
