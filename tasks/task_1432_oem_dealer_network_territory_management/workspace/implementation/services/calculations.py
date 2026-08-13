"""Business calculations per scaffold section 1.3 / PRD section 3.

All monetary math uses Decimal with round-half-up to integer cents; scorecard
components use round-half-up to two decimals BEFORE weighting.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import db
from util import round_half_up_int, round_half_up_2dp


# ---------------------------------------------------------------------------
# tier_discount (PRD 3.3)
# ---------------------------------------------------------------------------

TIER_GOLD_THRESHOLD = Decimal("1.2")
TIER_SILVER_THRESHOLD = Decimal("1.0")
RATE_GOLD = Decimal("0.08")
RATE_SILVER = Decimal("0.05")
RATE_BRONZE = Decimal("0.02")


def quarter_of(date_str: str) -> tuple[int, int]:
    """(year, quarter) for a YYYY-MM-DD date string."""
    d = datetime_date(date_str)
    return d.year, (d.month - 1) // 3 + 1


def datetime_date(date_str: str) -> date:
    return date(int(date_str[0:4]), int(date_str[5:7]), int(date_str[8:10]))


def first_day_of_following_quarter(year: int, quarter: int) -> date:
    if quarter < 4:
        return date(year, 3 * quarter + 1, 1)
    return date(year + 1, 1, 1)


def tier_rate_for_ratio(ratio: Decimal) -> Decimal:
    if ratio >= TIER_GOLD_THRESHOLD:
        return RATE_GOLD
    if ratio >= TIER_SILVER_THRESHOLD:
        return RATE_SILVER
    return RATE_BRONZE


def tier_name_for_ratio(ratio: Decimal) -> str:
    if ratio >= TIER_GOLD_THRESHOLD:
        return "GOLD"
    if ratio >= TIER_SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


def provisional_discount_cents(list_price_cents: int, achieved_units: int, target_units: int) -> int:
    """PROVISIONAL variant: counted_units = achieved_units + 1."""
    ratio = Decimal(achieved_units + 1) / Decimal(target_units)
    rate = tier_rate_for_ratio(ratio)
    return round_half_up_int(Decimal(list_price_cents) * rate)


def find_target(dealer_id: str, year: int, quarter: int):
    for t in db.targets.values():
        if (
            t["dealer_id"] == dealer_id
            and t["period_year"] == year
            and t["period_quarter"] == quarter
        ):
            return t
    return None


def find_open_target(dealer_id: str, year: int, quarter: int):
    t = find_target(dealer_id, year, quarter)
    if t is None or t["status"] != "OPEN":
        return None
    return t


# ---------------------------------------------------------------------------
# warranty_claim_amount (PRD 3.5)
# ---------------------------------------------------------------------------

LABOR_RATE_BY_TIER = {"GOLD": 12000, "SILVER": 10000, "BRONZE": 8500}


def claim_amount_cents(parts_cost_cents: int, labor_hours, tier: str) -> int:
    rate = LABOR_RATE_BY_TIER.get(tier, LABOR_RATE_BY_TIER["BRONZE"])
    labor = Decimal(str(labor_hours)) * Decimal(rate)
    return parts_cost_cents + round_half_up_int(labor)


# ---------------------------------------------------------------------------
# floorplan_interest_accrual (PRD 3.4)
# ---------------------------------------------------------------------------

FREE_DAYS = 90
PAST_DUE_DAYS = 90
DEFAULT_DAYS = 270
DAILY_RATE_1 = Decimal("0.0002")  # days 91..180
DAILY_RATE_2 = Decimal("0.0004")  # days 181..270
DAILY_RATE_3 = Decimal("0.0006")  # days 271+


def advance_age_days(advance: dict, today: date) -> int:
    advance_date = datetime_date(advance["advance_date"])
    return (today - advance_date).days


def accrued_interest_cents(advance: dict, today: date) -> int:
    age = advance_age_days(advance, today)
    principal = advance["advance_cents"] - advance["paid_curtailments_cents"]
    b1 = max(0, min(age, 180) - FREE_DAYS)
    b2 = max(0, min(age, 270) - 180)
    b3 = max(0, age - 270)
    rate_sum = DAILY_RATE_1 * b1 + DAILY_RATE_2 * b2 + DAILY_RATE_3 * b3
    return round_half_up_int(Decimal(principal) * rate_sum)


# ---------------------------------------------------------------------------
# parts_return_credit + parts_return_allowance (PRD 3.6)
# ---------------------------------------------------------------------------

RESTOCK_PCT = Decimal("0.15")
RETURN_ALLOWANCE_PCT = Decimal("0.05")


def restock_pct_for(return_year: int, today: date) -> Decimal:
    """0.15 when the current logical date falls after June 30 of return_year."""
    if today > date(return_year, 6, 30):
        return RESTOCK_PCT
    return Decimal("0")


def return_credit_cents(lines: list, return_year: int, today: date) -> tuple[int, float]:
    """Per-line round-then-sum credit. Returns (credit_cents, restock_pct_applied)."""
    restock = restock_pct_for(return_year, today)
    total = 0
    for line in lines:
        line_value = Decimal(line["quantity"]) * Decimal(line["unit_credit_cents"])
        total += round_half_up_int(line_value * (Decimal("1") - restock))
    return total, float(restock)


def allowance_total_cents(dealer: dict) -> int:
    return round_half_up_int(RETURN_ALLOWANCE_PCT * Decimal(dealer["parts_purchases_ytd_cents"]))


def allowance_used_cents(dealer_id: str, return_year: int) -> int:
    return sum(
        r["credit_cents"]
        for r in db.parts_returns.values()
        if r["dealer_id"] == dealer_id
        and r["return_year"] == return_year
        and r["status"] in ("SUBMITTED", "CREDITED")
    )


# ---------------------------------------------------------------------------
# dealer_performance_score (PRD 3.8)
# ---------------------------------------------------------------------------

REQUIRED_ACTIVE_CERTS = 2
WEIGHT_SALES = Decimal("0.40")
WEIGHT_SERVICE = Decimal("0.25")
WEIGHT_TRAINING = Decimal("0.20")
WEIGHT_PARTS = Decimal("0.15")
TERMINATION_SCORE_THRESHOLD = Decimal("60")

SETTLED_CLAIM_STATUSES = {"PAID", "AUDIT_FLAGGED", "CHARGED_BACK", "DISPUTED"}


def compute_scorecard(dealer: dict, period_year: int, period_quarter: int, variant: str) -> dict:
    dealer_id = dealer["id"]

    # --- sales ---
    target = find_target(dealer_id, period_year, period_quarter)
    if target is None:
        sales_score = 0.0
    else:
        counted = target["achieved_units"]
        if variant == "INCLUSIVE":
            counted += sum(
                1
                for s in db.unit_sales.values()
                if s["dealer_id"] == dealer_id
                and s["status"] == "REPORTED"
                and quarter_of(s["sale_date"]) == (period_year, period_quarter)
            )
        ratio = Decimal(counted) / Decimal(target["target_units"])
        capped = min(ratio, Decimal("1.5"))
        sales_score = round_half_up_2dp(capped / Decimal("1.5") * Decimal(100))

    # --- service ---
    claims = [c for c in db.claims.values() if c["dealer_id"] == dealer_id]
    settled = sum(c["claim_amount_cents"] for c in claims if c["status"] in SETTLED_CLAIM_STATUSES)
    chargebacked = sum(
        c["chargeback_amount_cents"] or 0 for c in claims if c["status"] == "CHARGED_BACK"
    )
    if variant == "INCLUSIVE":
        chargebacked += sum(
            c["claim_amount_cents"]
            for c in claims
            if c["status"] in ("AUDIT_FLAGGED", "DISPUTED")
        )
    if settled == 0:
        service_score = 100.0
    else:
        service_score = round_half_up_2dp(
            Decimal(100) - Decimal(100) * Decimal(chargebacked) / Decimal(settled)
        )

    # --- training ---
    certs = [c for c in db.certifications.values() if c["dealer_id"] == dealer_id]
    active = sum(1 for c in certs if c["status"] == "ACTIVE")
    if variant == "INCLUSIVE":
        pending = sum(1 for c in certs if c["status"] == "PENDING_VERIFICATION")
        cert_units = Decimal(active) + Decimal("0.5") * pending
    else:
        cert_units = Decimal(active)
    training_score = round_half_up_2dp(
        Decimal(100) * min(cert_units, Decimal(REQUIRED_ACTIVE_CERTS)) / Decimal(REQUIRED_ACTIVE_CERTS)
    )

    # --- parts ---
    parts_score = 100.0 if dealer["stock_compliant"] else 0.0

    total = round_half_up_2dp(
        Decimal(str(sales_score)) * WEIGHT_SALES
        + Decimal(str(service_score)) * WEIGHT_SERVICE
        + Decimal(str(training_score)) * WEIGHT_TRAINING
        + Decimal(str(parts_score)) * WEIGHT_PARTS
    )

    return {
        "period_year": period_year,
        "period_quarter": period_quarter,
        "variant": variant,
        "sales_score": sales_score,
        "service_score": service_score,
        "training_score": training_score,
        "parts_score": parts_score,
        "total_score": total,
    }
