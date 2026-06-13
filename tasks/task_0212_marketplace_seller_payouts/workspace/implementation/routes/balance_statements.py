"""Balance statement endpoints (PRD §3.12).

Append-only snapshot: id + created_at only (PRD §2.4).
"""
from datetime import datetime, timezone

from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_int, parse_iso8601,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.ledger import HOLD_AVAILABLE

bp = Blueprint("balance_statements", __name__)


def _period_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@bp.post("/balance-statements")
def create_statement():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    body = get_json_body()
    require_fields(body, ["seller_id", "period_year", "period_month"])
    require_int(body["period_year"], "period_year", 2020, 2030)
    require_int(body["period_month"], "period_month", 1, 12)
    seller = fetch(db.sellers, body["seller_id"])
    ensure_seller_owns(role, user_id, seller["id"])

    year = body["period_year"]
    month = body["period_month"]
    start, end = _period_bounds(year, month)

    entries = [e for e in db.ledger_entries.values() if e["seller_id"] == seller["id"]]

    # opening = sum of prior AVAILABLE postings (created before period start).
    opening = sum(
        e["amount_cents"] for e in entries
        if e["hold_state"] == HOLD_AVAILABLE
        and parse_iso8601(e["created_at"]) < start
    )
    # closing = available at the period's end (prior + in-period AVAILABLE).
    closing = sum(
        e["amount_cents"] for e in entries
        if e["hold_state"] == HOLD_AVAILABLE
        and parse_iso8601(e["created_at"]) < end
    )
    # in-period credits / debits / payouts.
    in_period = [
        e for e in entries
        if start <= parse_iso8601(e["created_at"]) < end
    ]
    total_credits = sum(e["amount_cents"] for e in in_period if e["amount_cents"] > 0)
    total_debits = sum(e["amount_cents"] for e in in_period if e["amount_cents"] < 0)
    total_payouts = sum(
        e["amount_cents"] for e in in_period
        if e["source_type"] == "PAYOUT" and e["amount_cents"] < 0
    )

    statement = {
        "id": db.new_id(),
        "seller_id": seller["id"],
        "period_year": year,
        "period_month": month,
        "opening_balance_cents": opening,
        "closing_balance_cents": closing,
        "total_credits_cents": total_credits,
        "total_debits_cents": total_debits,
        "total_payouts_cents": total_payouts,
        "created_at": db.now_iso(),
    }
    db.balance_statements[statement["id"]] = statement
    return success(statement, status=201)


@bp.get("/balance-statements/<statement_id>")
def get_statement(statement_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    statement = fetch(db.balance_statements, statement_id)
    ensure_seller_owns(role, user_id, statement["seller_id"])
    return success(statement)


@bp.get("/balance-statements")
def list_statements():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.balance_statements.values())
    if role == ROLE_SELLER:
        items = [s for s in items if s["seller_id"] == user_id]
    seller_id = request.args.get("seller_id")
    if seller_id is not None:
        items = [s for s in items if s["seller_id"] == seller_id]
    period_year = request.args.get("period_year")
    if period_year is not None:
        items = [s for s in items if str(s["period_year"]) == period_year]
    period_month = request.args.get("period_month")
    if period_month is not None:
        items = [s for s in items if str(s["period_month"]) == period_month]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)
