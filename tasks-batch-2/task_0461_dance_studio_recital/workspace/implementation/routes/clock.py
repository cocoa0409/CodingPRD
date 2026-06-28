"""Logical clock (PRD 2.4) + past-due cascade on advance (PRD 3.9)."""
import calendar

from flask import Blueprint

from db import db, touch
from helpers import parse_iso_datetime, require_fields
from middleware import authenticate, get_json
from response import success
from services.billing import set_family_status

bp = Blueprint("clock", __name__)


def _due_date_of(invoice):
    """The due day of an invoice's billing_month: the term's monthly_billing_day
    within that 'YYYY-MM' month, clamped to the last day of the month."""
    term = db.terms.get(invoice["term_id"])
    if term is None:
        return None
    try:
        year_s, month_s = invoice["billing_month"].split("-")
        year, month = int(year_s), int(month_s)
    except (ValueError, AttributeError):
        return None
    day = term["monthly_billing_day"]
    last = calendar.monthrange(year, month)[1]
    day = min(day, last)
    from datetime import date
    return date(year, month, day)


def _apply_past_due_cascade():
    """Any OPEN invoice whose due day is now past flips to PAST_DUE and its
    family to DELINQUENT (PRD 3.9)."""
    clock_d = db.clock.date()
    for inv in list(db.invoices.values()):
        if inv["status"] != "OPEN":
            continue
        due = _due_date_of(inv)
        if due is None:
            continue
        if clock_d > due:
            inv["status"] = "PAST_DUE"
            touch(inv)
            set_family_status(inv["family_id"], "DELINQUENT")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_iso_datetime(body["to_iso8601"])
    _apply_past_due_cascade()
    return success({}, status=200)
