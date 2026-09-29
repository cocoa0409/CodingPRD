"""
Domain assertion helpers.

Thin, explicit wrappers that keep the individual tests readable. Every helper
asserts something the PRD states in prose; none of them re-implement a
calculation the tests are supposed to pin with literal expected values.
"""

from typing import Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMMON_FIELDS,
    PAYMENT_EVENT_COMMON_FIELDS,
    POSTURE_FROZEN_PCT,
    POSTURE_RESTRICTED_PCT,
    RALBD_ALERT_FLOOR_CENTS,
)


# --------------------------------------------------------------------------
# Common field block (PRD §2.4)
# --------------------------------------------------------------------------
def assert_common_fields(entity: dict) -> None:
    """Every entity except PaymentEvent carries id, created_at, updated_at, version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field '{field}': {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_payment_event_shape(event: dict) -> None:
    """A payment event carries id and created_at only: no updated_at, no version."""
    for field in PAYMENT_EVENT_COMMON_FIELDS:
        assert field in event, f"missing field '{field}': {sorted(event)}"
    assert is_valid_uuid(event["id"]), event["id"]
    assert is_iso8601_timestamp(event["created_at"]), event["created_at"]
    assert "updated_at" not in event, "PaymentEvent must not carry updated_at"
    assert "version" not in event, "PaymentEvent must not carry version"


def assert_version_is(entity: dict, expected: int) -> None:
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}"
    )


def assert_version_unchanged(before: dict, after: dict) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that must not mutate the row"
    )


# --------------------------------------------------------------------------
# Field presence / typing
# --------------------------------------------------------------------------
def assert_fields_present(entity: dict, fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


def assert_two_decimal_pct(value, label: str = "pct") -> None:
    """Fractions and percentages in this API are exact two-decimal numbers."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimals, got {value!r}"
    )


def assert_cents(value, label: str = "amount_cents") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


# --------------------------------------------------------------------------
# Sailing derived state (PRD §2.11, §3.9)
# --------------------------------------------------------------------------
def assert_posture_for_occupancy(sailing: dict) -> None:
    """Posture is derived from the rounded occupancy_pct, highest band first."""
    pct = float(sailing["occupancy_pct"])
    if pct >= POSTURE_FROZEN_PCT:
        expected = "FROZEN"
    elif pct >= POSTURE_RESTRICTED_PCT:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert sailing["inventory_posture"] == expected, (
        f"occupancy_pct {pct} implies posture {expected}, "
        f"got {sailing['inventory_posture']}"
    )


def assert_revenue_alert_consistent(sailing: dict) -> None:
    """revenue_alert is true exactly when ralbd_net_cents is below the alert floor."""
    expected = sailing["ralbd_net_cents"] < RALBD_ALERT_FLOOR_CENTS
    assert sailing["revenue_alert"] is expected, (
        f"ralbd_net_cents {sailing['ralbd_net_cents']} against floor "
        f"{RALBD_ALERT_FLOOR_CENTS} implies revenue_alert {expected}, "
        f"got {sailing['revenue_alert']}"
    )


# --------------------------------------------------------------------------
# Allotment capacity identity (PRD §2.7)
# --------------------------------------------------------------------------
def assert_capacity_identity(inventory: dict) -> None:
    """physical + effective_oversell == available + booked + group_held, when unfloored."""
    sellable = inventory["physical_cabins"] + inventory["effective_oversell_cabins"]
    consumed = (
        inventory["available_cabins"]
        + inventory["booked_cabins"]
        + inventory["group_held_cabins"]
    )
    assert sellable == consumed, (
        f"capacity identity broken: {inventory['physical_cabins']} + "
        f"{inventory['effective_oversell_cabins']} != "
        f"{inventory['available_cabins']} + {inventory['booked_cabins']} + "
        f"{inventory['group_held_cabins']}"
    )


def assert_allotment_counters(
    inventory: dict,
    booked_cabins: Optional[int] = None,
    group_held_cabins: Optional[int] = None,
    available_cabins: Optional[int] = None,
    effective_oversell_cabins: Optional[int] = None,
    waitlisted_bookings_count: Optional[int] = None,
    released_cabins_total: Optional[int] = None,
) -> None:
    expected = {
        "booked_cabins": booked_cabins,
        "group_held_cabins": group_held_cabins,
        "available_cabins": available_cabins,
        "effective_oversell_cabins": effective_oversell_cabins,
        "waitlisted_bookings_count": waitlisted_bookings_count,
        "released_cabins_total": released_cabins_total,
    }
    for field, want in expected.items():
        if want is not None:
            assert inventory[field] == want, (
                f"{field}: expected {want}, got {inventory[field]}"
            )


# --------------------------------------------------------------------------
# Booking parallel state (PRD §2.5)
# --------------------------------------------------------------------------
def assert_booking_state(
    booking: dict,
    booking_status: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> None:
    if booking_status is not None:
        assert booking["booking_status"] == booking_status, (
            f"booking_status: expected {booking_status}, "
            f"got {booking['booking_status']}"
        )
    if payment_status is not None:
        assert booking["payment_status"] == payment_status, (
            f"payment_status: expected {payment_status}, "
            f"got {booking['payment_status']}"
        )


def assert_money(booking: dict, **expected) -> None:
    """Assert a set of integer-cent booking fields in one call."""
    for field, want in expected.items():
        assert booking[field] == want, f"{field}: expected {want}, got {booking[field]}"


# --------------------------------------------------------------------------
# Settlement invariant (PRD §3.6)
# --------------------------------------------------------------------------
def assert_settlement_cash_identity(booking: dict) -> None:
    """After settlement the cash retained equals the final penalty exactly."""
    assert booking["cancellation_penalty_cents"] is not None, "not settled"
    assert booking["amount_paid_cents"] == booking["cancellation_penalty_cents"], (
        f"retained cash {booking['amount_paid_cents']} != final penalty "
        f"{booking['cancellation_penalty_cents']}"
    )


# --------------------------------------------------------------------------
# Ordering helpers (PRD §2.3)
# --------------------------------------------------------------------------
def assert_sorted_by(rows: list, field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows not ascending by {field}: {values}"


def ids_of(rows: list) -> list:
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------
# Instant comparison (PRD 2.5)
# --------------------------------------------------------------------------
def _normalise_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to 'YYYY-MM-DDTHH:MM:SS.mmm'.

    The PRD fixes the semantics of a stored instant but the fractional-second
    representation of a whole-second value is not pinned, so a comparison must
    treat '...T17:00:00Z' and '...T17:00:00.000Z' as the same instant.
    """
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"expected a UTC instant ending in Z, got {value!r}"
    text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
    else:
        head, frac = text, ""
    frac = (frac + "000")[:3]
    return f"{head}.{frac}"


def assert_instant_equals(actual, expected_iso8601: str, label: str = "instant") -> None:
    """Assert two UTC instants denote the same moment."""
    assert _normalise_instant(actual) == _normalise_instant(expected_iso8601), (
        f"{label}: expected {expected_iso8601}, got {actual}"
    )
