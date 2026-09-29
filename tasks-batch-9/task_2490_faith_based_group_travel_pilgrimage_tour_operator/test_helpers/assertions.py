"""Domain assertions and the PRD's own arithmetic, re-derived independently.

Every helper here restates a rule the PRD pins in prose, so that a test can
compare the API's answer against a figure computed the PRD's way rather than
against a hand-copied literal.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AGE_BAND_A_BP,
    AGE_BAND_B_BP,
    AGE_BAND_B_MIN_AGE,
    AGE_BAND_C_BP,
    AGE_BAND_C_MIN_AGE,
    AGE_BAND_D_BP,
    AGE_BAND_D_MIN_AGE,
    BOOKING_FEE_BP,
    GRANT_TIER_HIGH_BP,
    GRANT_TIER_HIGH_THRESHOLD_CENTS,
    GRANT_TIER_MID_BP,
    GRANT_TIER_MID_THRESHOLD_CENTS,
    MEDICAL_UPLIFT_BP,
    MEDICAL_UPLIFT_THRESHOLD_CENTS,
    WAIVER_SURCHARGE_BP,
    WAIVER_SURCHARGE_CAP_CENTS,
)

# ---------------------------------------------------------------------------
# Basis-point arithmetic (PRD §2.6)
# ---------------------------------------------------------------------------


def apply_bp(amount_cents: int, rate_bp: int) -> int:
    """Multiply by a basis-point rate, divide by 10,000, round half up."""
    return int(
        (Decimal(amount_cents) * Decimal(rate_bp) / Decimal(10_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


# ---------------------------------------------------------------------------
# Invoice total (PRD §3.5, six pinned steps)
# ---------------------------------------------------------------------------


def expected_invoice_total(
    effective_price_cents: int,
    single_supplement_cents: int = 0,
    deviation_fee_cents: int = 0,
) -> int:
    gross = effective_price_cents + single_supplement_cents + deviation_fee_cents
    if gross >= GRANT_TIER_HIGH_THRESHOLD_CENTS:
        grant_bp = GRANT_TIER_HIGH_BP
    elif gross >= GRANT_TIER_MID_THRESHOLD_CENTS:
        grant_bp = GRANT_TIER_MID_BP
    else:
        grant_bp = 0
    grant = apply_bp(gross, grant_bp)
    net = gross - grant
    fee = apply_bp(net, BOOKING_FEE_BP)
    return net + fee


def assert_invoice_total(pilgrim: dict[str, Any], expected_cents: int) -> None:
    assert pilgrim["invoice_total_cents"] == expected_cents, (
        f"invoice_total_cents {pilgrim['invoice_total_cents']} != {expected_cents}"
    )


# ---------------------------------------------------------------------------
# Protection premium (PRD §3.8)
# ---------------------------------------------------------------------------


def expected_age_band(age_at_departure: int) -> str:
    if age_at_departure >= AGE_BAND_D_MIN_AGE:
        return "D"
    if age_at_departure >= AGE_BAND_C_MIN_AGE:
        return "C"
    if age_at_departure >= AGE_BAND_B_MIN_AGE:
        return "B"
    return "A"


def expected_base_premium(insured_trip_cost_cents: int, age_at_departure: int) -> int:
    band = expected_age_band(age_at_departure)
    rate = {
        "D": AGE_BAND_D_BP,
        "C": AGE_BAND_C_BP,
        "B": AGE_BAND_B_BP,
        "A": AGE_BAND_A_BP,
    }[band]
    return apply_bp(insured_trip_cost_cents, rate)


def expected_medical_uplift(base_premium_cents: int, medical_limit_cents: int) -> int:
    """Uplift applies only when the limit is strictly above 5,000,000 cents."""
    if medical_limit_cents > MEDICAL_UPLIFT_THRESHOLD_CENTS:
        return apply_bp(base_premium_cents, MEDICAL_UPLIFT_BP)
    return 0


def expected_waiver_surcharge(base_premium_cents: int) -> int:
    """Rounded first, then capped at 45,000 cents."""
    return min(WAIVER_SURCHARGE_CAP_CENTS, apply_bp(base_premium_cents, WAIVER_SURCHARGE_BP))


def assert_premium_decomposition(
    protection: dict[str, Any],
    base_cents: int,
    uplift_cents: int,
    surcharge_cents: int,
) -> None:
    assert protection["base_premium_cents"] == base_cents
    assert protection["medical_uplift_cents"] == uplift_cents
    assert protection["waiver_surcharge_cents"] == surcharge_cents
    assert protection["premium_cents"] == base_cents + uplift_cents + surcharge_cents


# ---------------------------------------------------------------------------
# Land line conversion (PRD §3.3)
# ---------------------------------------------------------------------------


def days_inclusive(date_from: str, date_to: str) -> int:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    return (end - start).days + 1


def expected_land_line(
    units_requested: int, date_from: str, date_to: str, unit_rate_local_cents: int, fx_rate_bp: int
) -> tuple[int, int, int]:
    """Return (days_inclusive, line_local_cents, line_usd_cents)."""
    days = days_inclusive(date_from, date_to)
    local = units_requested * days * unit_rate_local_cents
    usd = apply_bp(local, fx_rate_bp)
    return days, local, usd


# ---------------------------------------------------------------------------
# Cancellation settlement (PRD §3.5)
# ---------------------------------------------------------------------------


def select_cancellation_bp(grid: Iterable[dict[str, Any]], days_before: int) -> int:
    """The bucket with the greatest reachable `min_days_before`; negatives use 0."""
    effective = max(days_before, 0)
    best: dict[str, Any] | None = None
    for bucket in grid:
        if bucket["min_days_before"] <= effective:
            if best is None or bucket["min_days_before"] > best["min_days_before"]:
                best = bucket
    assert best is not None, "cancellation grid must contain a 0 bucket"
    return int(best["penalty_bp"])


def expected_penalty_and_refund(
    invoice_total_cents: int, cash_applied_cents: int, penalty_bp: int
) -> tuple[int, int]:
    penalty = min(cash_applied_cents, apply_bp(invoice_total_cents, penalty_bp))
    return penalty, cash_applied_cents - penalty


# ---------------------------------------------------------------------------
# Leader accrual (PRD §3.4)
# ---------------------------------------------------------------------------


def expected_commission(
    recruited_paying_count: int,
    free_travel_threshold: int,
    commission_mode: str,
    commission_rate_cents_per_pax: int,
    per_pax_price_cents: int,
) -> tuple[int, int]:
    """Return (earned_free_seats, commission_cents)."""
    earned = recruited_paying_count // free_travel_threshold
    gross = recruited_paying_count * commission_rate_cents_per_pax
    if commission_mode == "PER_PAX_CASH":
        return earned, gross
    if commission_mode == "FREE_SEAT_CREDIT":
        return earned, 0
    return earned, max(0, gross - earned * per_pax_price_cents)


def assert_accrual_snapshot(
    agreement: dict[str, Any],
    recruited_paying_count: int,
    earned_free_seats: int,
    commission_payable_cents: int,
) -> None:
    assert agreement["recruited_paying_count"] == recruited_paying_count
    assert agreement["earned_free_seats"] == earned_free_seats
    assert agreement["commission_payable_cents"] == commission_payable_cents


def assert_settlement_snapshot(
    agreement: dict[str, Any],
    settled_recruited_count: int,
    settled_earned_free_seats: int,
    settled_commission_cents: int,
) -> None:
    assert agreement["settled_recruited_count"] == settled_recruited_count
    assert agreement["settled_earned_free_seats"] == settled_earned_free_seats
    assert agreement["settled_commission_cents"] == settled_commission_cents


# ---------------------------------------------------------------------------
# Installment schedules (PRD §3.7)
# ---------------------------------------------------------------------------


def expected_installment_amounts(invoice_total_cents: int, installment_count: int) -> list[int]:
    """Floor division, with the remainder cents on the earliest installments."""
    base = invoice_total_cents // installment_count
    remainder = invoice_total_cents - base * installment_count
    return [base + (1 if index < remainder else 0) for index in range(installment_count)]


def assert_installment(
    installment: dict[str, Any],
    amount_due_cents: int | None = None,
    amount_paid_cents: int | None = None,
    status: str | None = None,
) -> None:
    if amount_due_cents is not None:
        assert installment["amount_due_cents"] == amount_due_cents
    if amount_paid_cents is not None:
        assert installment["amount_paid_cents"] == amount_paid_cents
    if status is not None:
        assert installment["status"] == status


# ---------------------------------------------------------------------------
# Buffered service intervals (PRD §3.2)
# ---------------------------------------------------------------------------


def expected_buffered_end(
    scheduled_start_utc: str, duration_minutes: int, turnaround_buffer_minutes: int
) -> str:
    start = datetime.fromisoformat(scheduled_start_utc.replace("Z", "+00:00"))
    end = start + timedelta(minutes=duration_minutes + turnaround_buffer_minutes)
    return end.strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_instant_equals(actual: str, expected: str) -> None:
    """Compare two RFC3339 UTC instants by value, not by spelling.

    §2.5 fixes three fractional digits on `created_at` and `updated_at` but the
    other instant fields carry no stated precision, so `2026-11-02T07:30:00Z`
    and `2026-11-02T07:30:00.000Z` denote the same instant and both are correct.
    """
    assert is_iso8601_timestamp(actual), f"Not a valid ISO 8601 instant: {actual!r}"
    parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    wanted = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed == wanted, f"instant {actual!r} is not {expected!r}"


# ---------------------------------------------------------------------------
# Age at departure (PRD §3.5)
# ---------------------------------------------------------------------------


def expected_age_at_departure(date_of_birth: str, departure_date: str) -> int:
    born = date.fromisoformat(date_of_birth)
    depart = date.fromisoformat(departure_date)
    years = depart.year - born.year
    if (depart.month, depart.day) < (born.month, born.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Row shape (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(row: dict[str, Any], expected_version: int | None = None) -> None:
    """The four columns twelve of the thirteen record types share."""
    assert is_valid_uuid(row["id"]), f"id {row['id']!r} is not a bare UUID"
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int)
    if expected_version is not None:
        assert row["version"] == expected_version


def assert_receipt_fields(row: dict[str, Any]) -> None:
    """A `Payment` row carries only `id` and `created_at` of the common columns."""
    assert is_valid_uuid(row["id"]), f"id {row['id']!r} is not a bare UUID"
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row, "a cash receipt must not carry updated_at"
    assert "version" not in row, "a cash receipt must not carry version"


def assert_version_bumped(before: dict[str, Any], after: dict[str, Any], by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version moved {before['version']} -> {after['version']}, expected +{by}"
    )


# ---------------------------------------------------------------------------
# Conservation identities (PRD §2.10)
# ---------------------------------------------------------------------------


def assert_cash_conservation(
    pilgrim: dict[str, Any], plans: Iterable[dict[str, Any]]
) -> None:
    """Installment cash of live plans plus credit equals `cash_applied_cents`."""
    allocated = 0
    for plan in plans:
        if plan["status"] in ("ACTIVE", "COMPLETED", "DEFAULTED"):
            allocated += sum(item["amount_paid_cents"] for item in plan["installments"])
    total = allocated + pilgrim["credit_balance_cents"]
    assert total == pilgrim["cash_applied_cents"], (
        f"allocated {allocated} + credit {pilgrim['credit_balance_cents']} "
        f"!= cash_applied {pilgrim['cash_applied_cents']}"
    )


def assert_site_capacity(
    bookings: Iterable[dict[str, Any]], utc_date: str, expected_occupied_pax: int
) -> None:
    """Occupied pax on a date is the sum over non-CANCELLED bookings."""
    occupied = sum(
        booking["pax_count"]
        for booking in bookings
        if booking["status"] in ("SITE_HELD", "CLERGY_CONFIRMED", "CONFIRMED")
        and booking["scheduled_start_utc"].startswith(utc_date)
    )
    assert occupied == expected_occupied_pax, (
        f"occupied pax on {utc_date} is {occupied}, expected {expected_occupied_pax}"
    )


__all__ = [
    "apply_bp",
    "assert_accrual_snapshot",
    "assert_cash_conservation",
    "assert_common_fields",
    "assert_installment",
    "assert_instant_equals",
    "assert_invoice_total",
    "assert_premium_decomposition",
    "assert_receipt_fields",
    "assert_settlement_snapshot",
    "assert_site_capacity",
    "assert_version_bumped",
    "days_inclusive",
    "expected_age_at_departure",
    "expected_age_band",
    "expected_base_premium",
    "expected_buffered_end",
    "expected_commission",
    "expected_installment_amounts",
    "expected_invoice_total",
    "expected_land_line",
    "expected_medical_uplift",
    "expected_penalty_and_refund",
    "expected_waiver_surcharge",
    "select_cancellation_bp",
]
