"""IFTA quarterly fuel-tax computation (PRD §3.9)."""
import re
from datetime import datetime, timezone

from util import dec, num, round_cents, round_half_up
from services.store import TAX_RATE_CENTS, account_transactions

QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")

_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}


def quarter_period(quarter):
    """(period_start, period_end) as tz-aware UTC datetimes; end is exclusive."""
    year = int(quarter[:4])
    q = int(quarter[-1])
    start_month = _QUARTER_START_MONTH[q]
    start = datetime(year, start_month, 1, tzinfo=timezone.utc)
    if q == 4:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, start_month + 3, 1, tzinfo=timezone.utc)
    return start, end


def in_period(txn, start, end):
    return start <= txn["_purchased_at_dt"] < end


def period_transactions(account_id, start, end):
    """Every transaction of the account whose purchased_at lies in the half-open period."""
    return [t for t in account_transactions(account_id) if in_period(t, start, end)]


def compute(account_id, start, end):
    """Returns (jurisdiction_lines, total_tax_cents) over the period's SETTLED transactions."""
    settled = [t for t in period_transactions(account_id, start, end)
               if t["posting_status"] == "SETTLED"]

    total_gallons = sum((dec(t["gallons"]) for t in settled), dec(0))
    if total_gallons == 0:
        # fleet economy treated as zero -> the report has no jurisdiction lines
        return [], 0

    total_miles = sum((dec(t["segment_miles"]) for t in settled), dec(0))
    fleet_mpg = total_miles / total_gallons

    lines = []
    total_tax = 0
    for jurisdiction in sorted({t["jurisdiction"] for t in settled}):
        rows = [t for t in settled if t["jurisdiction"] == jurisdiction]
        miles_j = sum((dec(t["segment_miles"]) for t in rows), dec(0))
        gallons_j = sum((dec(t["gallons"]) for t in rows), dec(0))
        rate = TAX_RATE_CENTS.get(jurisdiction, 0)

        if fleet_mpg == 0:
            taxable = dec(0)
        else:
            taxable = round_half_up(miles_j / fleet_mpg, 3)

        # tax owed on taxable gallons, less the credit for tax already paid at the
        # pump — each part rounded to cents HALF UP first, then subtracted.
        net_tax = round_cents(taxable * dec(rate)) - round_cents(gallons_j * dec(rate))

        lines.append({
            "jurisdiction": jurisdiction,
            "miles": num(miles_j),
            "gallons_purchased": num(gallons_j),
            "taxable_gallons": float(taxable),
            "tax_rate_cents": rate,
            "net_tax_cents": net_tax,
        })
        total_tax += net_tax

    return lines, total_tax
