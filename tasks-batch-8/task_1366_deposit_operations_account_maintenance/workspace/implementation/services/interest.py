"""Accrued-interest settlement (PRD §2.6, §2.7; SCAFFOLD §1.3).

Window: half-open [accrual_start_date, settlement_date); one accrual step per
calendar day. A day's balance is the end-of-day balance — balance_after_cents
of the last transaction with posted_date <= that day (carry forward; zero
before the first transaction). ALL transaction types move the balance.

Raw daily interest is the exact rational balance * rate_bps / 10000 / 365.
STANDARD variant (BASIC_CHECKING, PREMIUM_CHECKING, SAVINGS): round each day
half-up, then sum. SIMPLE variant (MONEY_MARKET): sum exact daily amounts,
round half-up once at the end.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

DAYS_IN_YEAR = 365

STANDARD_PRODUCTS = {"BASIC_CHECKING", "PREMIUM_CHECKING", "SAVINGS"}
SIMPLE_PRODUCTS = {"MONEY_MARKET"}

VARIANT_STANDARD = "STANDARD"
VARIANT_SIMPLE = "SIMPLE"


def rounding_variant_for_product(product_code: str) -> str:
    return VARIANT_SIMPLE if product_code in SIMPLE_PRODUCTS else VARIANT_STANDARD


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _daily_balance_series(account_id: str, start: date, end: date):
    """Yield the end-of-day balance for each day d in [start, end)."""
    txns = [t for t in db.transactions.values() if t["account_id"] == account_id]
    # Balance state at the END of day (start - 1): last txn posted before start.
    prior = [t for t in txns if _parse_date(t["posted_date"]) < start]
    prior.sort(key=lambda t: t["_seq"])
    balance = prior[-1]["balance_after_cents"] if prior else 0

    by_day = {}
    for t in txns:
        by_day.setdefault(_parse_date(t["posted_date"]), []).append(t)
    for lst in by_day.values():
        lst.sort(key=lambda t: t["_seq"])

    d = start
    while d < end:
        if d in by_day:
            balance = by_day[d][-1]["balance_after_cents"]
        yield balance
        d += timedelta(days=1)


def accrued_interest(account_id: str, start_date_str: str, settlement_date_str: str,
                     rate_bps: int, variant: str) -> int:
    """Integer cents of interest accrued over [start_date, settlement_date)."""
    start = _parse_date(start_date_str)
    end = _parse_date(settlement_date_str)
    if end <= start or rate_bps <= 0:
        return 0

    rate = Decimal(rate_bps) / Decimal(10000) / Decimal(DAYS_IN_YEAR)

    if variant == VARIANT_STANDARD:
        total = 0
        for bal in _daily_balance_series(account_id, start, end):
            raw = Decimal(bal) * rate
            total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return total

    # SIMPLE: sum exact daily amounts, round once at the end.
    raw_total = Decimal(0)
    for bal in _daily_balance_series(account_id, start, end):
        raw_total += Decimal(bal) * rate
    return int(raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
