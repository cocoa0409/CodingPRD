"""PriceQuote accept endpoint."""
from flask import Blueprint

from db import db
from errors import (
    err_credit_limit_exceeded,
    err_grade_discontinued,
    err_not_found,
    err_quote_expired,
    err_quote_not_open,
)
from middleware import require_roles
from response import success_object
from services.calcs import bump, recompute_credit_exposure
from services.clock import get_logical_clock
from services.serialize import serialize_price_quote
from util import D, parse_date
from ._helpers import get_json_body

bp = Blueprint("quotes", __name__)


@bp.route("/api/price-quotes/<qid>/accept", methods=["POST"])
@require_roles("SalesRep")
def accept_quote(qid, _user_id, _role):
    q = db.price_quotes.get(qid)
    if q is None:
        raise err_not_found("price quote not found")

    # State: quote must be OPEN
    if q["status"] != "OPEN":
        raise err_quote_not_open(f"quote status is {q['status']}, not OPEN")

    # Expiry check (temporal, per logical clock date)
    exp = parse_date(q["expires_on"])
    if exp is None:
        # Defensive: should never happen because creation validates the date
        raise err_quote_expired("quote expires_on is invalid")
    logical_date = get_logical_clock().date()
    if logical_date > exp:
        q["status"] = "EXPIRED"
        bump(q)
        raise err_quote_expired("logical clock date is later than quote.expires_on")

    # Grade must be ACTIVE at acceptance
    order = db.box_orders.get(q["order_id"])
    if order is None:
        raise err_not_found("parent order not found")
    grade = db.board_grades.get(order["board_grade_id"])
    if grade is None:
        raise err_not_found("board grade not found")
    if grade["status"] != "ACTIVE":
        raise err_grade_discontinued("referenced board grade is DISCONTINUED")

    # Credit limit check
    cust = db.customer_accounts.get(order["customer_id"])
    if cust is None:
        raise err_not_found("customer not found")
    exposure = D(cust["credit_exposure_dollars"])
    total = D(q["quote_total_dollars"])
    limit = D(cust["credit_limit_dollars"])
    if exposure + total > limit:
        raise err_credit_limit_exceeded("acceptance would push customer exposure above credit_limit_dollars")

    # Success path: quote OPEN -> ACCEPTED, every other OPEN quote on the order -> SUPERSEDED
    for other in db.price_quotes.values():
        if other["order_id"] == order["id"] and other["status"] == "OPEN" and other["id"] != q["id"]:
            other["status"] = "SUPERSEDED"
            bump(other)

    q["status"] = "ACCEPTED"
    bump(q)

    order["status"] = "ACCEPTED"
    order["committed_value_dollars"] = D(q["quote_total_dollars"])
    bump(order)

    recompute_credit_exposure(cust)
    bump(cust)

    return success_object(serialize_price_quote(q), 200)
