"""Resale certificate payoff calculation and cascade voiding (PRD 3.9)."""
import calendar
from datetime import datetime, timezone

import clock
import db
import money
from services import alloc, ledger

TERMINAL_CASE_STATUSES = ("CURED", "DISMISSED", "FINE_UPHELD", "FINE_VACATED")


def _month_start(dt):
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


def _next_month(dt):
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)


def special_assessment_disclosure(unit):
    """Unbilled remainder of every APPROVED special assessment of the association
    allocable to this unit."""
    total = 0
    for sa in db.sorted_rows("special_assessments",
                             lambda s: s["association_id"] == unit["association_id"]
                             and s["approval_status"] == "APPROVED"):
        shares = alloc.sa_full_shares(sa)
        share = shares.get(unit["id"], 0)
        billed = sum(
            e["amount_cents"] for e in db.store["ledger_entries"].values()
            if e["unit_id"] == unit["id"] and e["status"] == "POSTED"
            and e["entry_type"] == "SPECIAL_ASSESSMENT_INSTALLMENT"
            and e.get("special_assessment_id") == sa["id"]
        )
        total += share - billed
    return total


def open_violation_count(unit):
    return sum(1 for c in db.store["violation_cases"].values()
               if c["unit_id"] == unit["id"]
               and c["status"] not in TERMINAL_CASE_STATUSES)


def disclosed_claim_ids(association_id):
    rows = db.sorted_rows("insurance_claims",
                          lambda c: c["association_id"] == association_id
                          and c.get("disclosure_required"))
    return [c["id"] for c in rows]


def future_period_count(unit, closing_date):
    """Whole billing periods whose first day falls strictly after the logical clock
    and strictly before closing_date and for which the unit has no POSTED
    ASSESSMENT row yet."""
    now = clock.now()
    cursor = _next_month(now) if _month_start(now) <= now else _month_start(now)
    count = 0
    guard = 0
    while cursor < closing_date and guard < 2400:
        guard += 1
        if cursor > now:
            period = "%04d-%02d" % (cursor.year, cursor.month)
            billed = any(
                e["unit_id"] == unit["id"] and e["status"] == "POSTED"
                and e["entry_type"] == "ASSESSMENT"
                and e["effective_period"] == period
                for e in db.store["ledger_entries"].values()
            )
            if not billed:
                count += 1
        cursor = _next_month(cursor)
    return count


def payoff(unit, closing_date, payoff_basis):
    """Returns the payoff / disclosure payload dict."""
    month_start = _month_start(closing_date)
    month_days = calendar.monthrange(closing_date.year, closing_date.month)[1]
    seller_days = clock.floor_days(closing_date, month_start)
    buyer_days = month_days - seller_days

    balance = unit["balance_due_cents"]
    unbilled_sa = special_assessment_disclosure(unit)

    if payoff_basis == "ESTIMATED_PAYOFF":
        periods = future_period_count(unit, closing_date)
        gross = balance + periods * unit["monthly_assessment_cents"] + unbilled_sa
        proration = money.round_half_up(
            unit["monthly_assessment_cents"] * buyer_days, month_days)
        projected = gross - proration
    else:
        proration = 0
        projected = balance

    return {
        "ledger_balance_cents": balance,
        "projected_payoff_cents": projected,
        "proration_credit_cents": proration,
        "open_violation_count": open_violation_count(unit),
        "special_assessment_disclosure_cents": unbilled_sa,
        "disclosed_claim_ids": disclosed_claim_ids(unit["association_id"]),
    }


def fiscal_year_containing(assoc, when):
    """The fiscal year label whose span contains `when`, honouring a fiscal year
    that does not start in January."""
    start_month = assoc.get("fiscal_year_start_month", 1) or 1
    return when.year - 1 if when.month < start_month else when.year


def adopted_budget_for(assoc, when):
    """The ADOPTED budget of the association whose fiscal_year contains `when`."""
    target = fiscal_year_containing(assoc, when)
    for b in db.sorted_rows("budgets",
                            lambda x: x["association_id"] == assoc["id"]
                            and x["status"] == "ADOPTED"):
        if b["fiscal_year"] == target:
            return b
    return None


def cascade_void(cert, unit=None):
    """A cascade void: requires_reissue true, the RESALE_FEE row is answered with a
    REVERSAL, and the unit is recomputed with Unit.version advancing by 1."""
    if unit is None:
        unit = db.get("units", cert["unit_id"])
    cert["status"] = "VOIDED"
    cert["requires_reissue"] = True
    fee = db.get("ledger_entries", cert.get("cert_fee_entry_id"))
    if fee is not None and fee["status"] == "POSTED":
        ledger.reverse_entry(unit, fee, memo="Certificate voided by cascade")
    if unit is not None:
        ledger.recompute_unit(unit)
    db.touch(cert)
    return cert
