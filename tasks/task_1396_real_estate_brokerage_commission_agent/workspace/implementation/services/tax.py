"""1099 totals (PRD §3.9): cash basis (filed) and accrual basis (informational)."""

from datetime import datetime, timezone

import db
from timeutil import parse_iso8601

FILING_THRESHOLD_CENTS = 60000

# Payee types that count as contractor compensation
_COMP_TYPES = ("AGENT", "MENTOR", "TEAM_LEAD", "REFERRAL")


def _year_bounds(tax_year):
    start = datetime(tax_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


def compute_totals(agent_id, tax_year):
    start, end = _year_bounds(tax_year)

    # Cash basis: RELEASED legs payable to the agent, keyed on released_at
    gross_paid = 0
    for leg in db.legs.values():
        if leg.get("payee_agent_id") != agent_id:
            continue
        if leg["payee_type"] not in _COMP_TYPES:
            continue
        if leg["status"] != "RELEASED" or not leg.get("released_at"):
            continue
        ts = parse_iso8601(leg["released_at"])
        if start <= ts < end:
            gross_paid += leg["amount_cents"]

    # Accrual basis: own POSTED settlements posted in the year + MENTOR /
    # TEAM_LEAD / REFERRAL legs payable to the agent created in the year
    # (any non-VOIDED status).
    accrual = 0
    for s in db.settlements.values():
        if s["agent_id"] != agent_id or s["status"] != "POSTED":
            continue
        ts = parse_iso8601(s["posted_at"])
        if start <= ts < end:
            accrual += s["agent_gross_cents"]
    for leg in db.legs.values():
        if leg.get("payee_agent_id") != agent_id:
            continue
        if leg["payee_type"] not in ("MENTOR", "TEAM_LEAD", "REFERRAL"):
            continue
        if leg["status"] == "VOIDED":
            continue
        ts = parse_iso8601(leg["created_at"])
        if start <= ts < end:
            accrual += leg["amount_cents"]

    return {
        "gross_paid_cents": gross_paid,
        "accrual_gross_cents": accrual,
        "filing_required": gross_paid >= FILING_THRESHOLD_CENTS,
    }
