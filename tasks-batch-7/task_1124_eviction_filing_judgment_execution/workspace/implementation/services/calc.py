"""Jurisdictional schedules and calculation rules (scaffold §1.3)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

CURE_DAYS = {
    "CA": {"PAY_OR_QUIT": 3, "CURE_OR_QUIT": 3, "UNCONDITIONAL_QUIT": 0},
    "TX": {"PAY_OR_QUIT": 3, "CURE_OR_QUIT": 5, "UNCONDITIONAL_QUIT": 0},
    "OH": {"PAY_OR_QUIT": 5, "CURE_OR_QUIT": 7, "UNCONDITIONAL_QUIT": 0},
}

FILING_BASE_TIERS = {
    "CA": [(250000, 24000), (1000000, 32000), (None, 43500)],
    "TX": [(200000, 18500), (800000, 26000), (None, 35000)],
    "OH": [(150000, 15000), (500000, 21000), (None, 30000)],
}
DEFENDANT_SURCHARGE_CENTS = 2500
JURY_FEE_CENTS = 15000
VARIANT_ADJ = {True: -1000, False: 750}  # efiled -> ELECTRONIC discount; else STANDARD surcharge

ANNUAL_RATE = {"CA": Decimal("0.10"), "TX": Decimal("0.06"), "OH": Decimal("0.08")}
APPEAL_DAYS = {"CA": 5, "TX": 5, "OH": 10}

WRIT_FEE = {"CA": 4000, "TX": 3500, "OH": 2500}
WRIT_VALID_DAYS = {"CA": 30, "TX": 30, "OH": 30}

HEARING_LEAD_DAYS = {"CA": 10, "TX": 8, "OH": 12}

STORAGE_DAILY_FEE = {"CA": 1500, "TX": 1000, "OH": 800}
STORAGE_BILLING_MODE = {"CA": "CALENDAR_INCLUSIVE", "TX": "ELAPSED_24H", "OH": "ELAPSED_24H"}
STORAGE_DAYS = {"CA": 15, "TX": 14, "OH": 30}

MAX_LOCKOUTS_PER_DEPUTY_DAY = 3

NOTICE_TYPE_REASON = {
    "PAY_OR_QUIT": "NONPAYMENT",
    "CURE_OR_QUIT": "LEASE_VIOLATION",
    "UNCONDITIONAL_QUIT": "SEVERE",
}

WATERFALL_ORDER = ["court_costs", "late_fees", "damages", "interest", "rent"]


def filing_fee(jurisdiction, claimed_amount_cents, n_defendants, jury_demanded, efiled):
    base = next(
        fee
        for cap, fee in FILING_BASE_TIERS[jurisdiction]
        if cap is None or claimed_amount_cents <= cap
    )
    fee = (
        base
        + DEFENDANT_SURCHARGE_CENTS * n_defendants
        + (JURY_FEE_CENTS if jury_demanded else 0)
        + VARIANT_ADJ[bool(efiled)]
    )
    return max(0, fee)


def judgment_interest(jurisdiction, principal_cents, days_overdue):
    """Per-diem rounded half-up FIRST, then multiplied by days (order pinned)."""
    daily = (Decimal(principal_cents) * ANNUAL_RATE[jurisdiction] / Decimal(365)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(daily) * days_overdue


def storage_charge(billing_mode, daily_fee_cents, stored_at, now_dt):
    if billing_mode == "CALENDAR_INCLUSIVE":
        days = (now_dt.date() - stored_at.date()).days + 1
        chargeable_days = max(1, days)
    else:  # ELAPSED_24H
        elapsed_seconds = max(0.0, (now_dt - stored_at).total_seconds())
        chargeable_days = math.ceil(elapsed_seconds / 86400.0) if elapsed_seconds > 0 else 0
    return chargeable_days * daily_fee_cents


def disposal_eligible_on(jurisdiction, stored_at):
    return stored_at + timedelta(days=STORAGE_DAYS[jurisdiction])
