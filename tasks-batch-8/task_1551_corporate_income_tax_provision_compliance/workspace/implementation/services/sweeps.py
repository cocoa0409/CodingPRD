"""Logical-clock sweeps (PRD §2.7): run synchronously inside the clock-advance
request. Returns (late_payment_ids, overdue_notice_ids, lapsed_position_ids)
in store (creation) order.
"""
from db import db, touch, bump_year
from services.calc import (
    STATUTE_YEARS,
    compute_underpayment_penalty,
    recompute_utp_reserve,
    recompute_etrs,
)
from util import parse_date, add_years


def run_sweeps(today):
    late_payment_ids = []
    overdue_notice_ids = []
    lapsed_position_ids = []

    # Estimated payments: SCHEDULED/PARTIALLY_PAID, due date passed, strict shortfall.
    for p in list(db.payments.values()):
        if (p["status"] in ("SCHEDULED", "PARTIALLY_PAID")
                and parse_date(p["due_date"]) < today
                and p["paid_amount_cents"] < p["scheduled_amount_cents"]):
            p["status"] = "LATE"
            p["penalty_cents"] = compute_underpayment_penalty(
                p["scheduled_amount_cents"], p["paid_amount_cents"])
            touch(p)
            late_payment_ids.append(p["id"])

    # Notices: RECEIVED/UNDER_REVIEW past their response deadline.
    for n in list(db.notices.values()):
        if (n["status"] in ("RECEIVED", "UNDER_REVIEW")
                and parse_date(n["response_due_on"]) < today):
            n["status"] = "OVERDUE"
            touch(n)
            overdue_notice_ids.append(n["id"])

    # Uncertain tax positions: DISCLOSED, statute of limitation (filed_on + 3 years) passed.
    for pos in list(db.utps.values()):
        if pos["status"] != "DISCLOSED":
            continue
        filed = [f for f in db.filings.values()
                 if f["tax_year_id"] == pos["tax_year_id"]
                 and f["jurisdiction_id"] == pos["jurisdiction_id"]
                 and f["status"] in ("FILED", "ACCEPTED") and f["filed_on"]]
        if not filed:
            continue
        latest_filed_on = max(parse_date(f["filed_on"]) for f in filed)
        if today > add_years(latest_filed_on, STATUTE_YEARS):
            pos["status"] = "LAPSED"
            touch(pos)
            lapsed_position_ids.append(pos["id"])
            year = db.tax_years.get(pos["tax_year_id"])
            if year is not None:
                recompute_utp_reserve(year)
                recompute_etrs(year)
                bump_year(year)

    return late_payment_ids, overdue_notice_ids, lapsed_position_ids
