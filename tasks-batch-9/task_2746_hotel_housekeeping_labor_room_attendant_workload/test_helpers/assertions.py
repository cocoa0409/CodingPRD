"""Domain assertion helpers for the Hotel Housekeeping Labor & Workload API.

Each helper encodes a precision or shape commitment stated in the PRD:
credits at two decimals snapped to quarters (PRD 2.6), `score_pct` at one
decimal, `coverage_ratio` at four decimals, `credit_variance_pct` signed at two
decimals, whole-minute truncation, and the linen ledger identity of PRD 2.11.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import pytest

from .constants import (
    COVERAGE_TOLERANCE,
    CREDIT_QUANTUM,
    CREDIT_TOLERANCE,
    MAX_ASSIGNMENT_CREDITS,
    MIN_ASSIGNMENT_CREDITS,
    PCT_TOLERANCE,
    SCORE_TOLERANCE,
)

# --------------------------------------------------------------------------
# Numeric precision
# --------------------------------------------------------------------------


def assert_credits(actual: Any, expected: float, label: str = "credits") -> None:
    """Assert a two-decimal credit figure (PRD 2.6)."""
    assert actual is not None, f"{label} must not be null"
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert float(actual) == pytest.approx(expected, abs=CREDIT_TOLERANCE), (
        f"{label} should be {expected:.2f}, got {actual}"
    )


def assert_snapped_to_quarter(actual: Any, label: str = "credits") -> None:
    """Assert an assignment credit figure is a whole number of quarter credits."""
    assert actual is not None, f"{label} must not be null"
    quarters = float(actual) / CREDIT_QUANTUM
    assert abs(quarters - round(quarters)) < 1e-6, (
        f"{label}={actual} is not snapped to 0.25 credit units"
    )
    assert float(actual) >= MIN_ASSIGNMENT_CREDITS - 1e-9, (
        f"{label}={actual} is below the 0.25 credit floor"
    )
    assert float(actual) <= MAX_ASSIGNMENT_CREDITS + 1e-9, (
        f"{label}={actual} is above the 3.00 credit ceiling"
    )


def assert_score_pct(actual: Any, expected: float) -> None:
    """Assert `Inspection.score_pct`, carried to one decimal place (PRD 2.6)."""
    assert actual is not None, "score_pct must not be null"
    assert float(actual) == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"score_pct should be {expected:.1f}, got {actual}"
    )


def assert_coverage_ratio(actual: Any, expected: float) -> None:
    """Assert `LinenItem.coverage_ratio`, carried to four decimals (PRD 2.6)."""
    assert actual is not None, "coverage_ratio must not be null"
    assert float(actual) == pytest.approx(expected, abs=COVERAGE_TOLERANCE), (
        f"coverage_ratio should be {expected:.4f}, got {actual}"
    )


def assert_variance_pct(actual: Any, expected: float) -> None:
    """Assert `ForecastDay.credit_variance_pct`, signed at two decimals."""
    assert actual is not None, "credit_variance_pct must not be null"
    assert float(actual) == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"credit_variance_pct should be {expected:.2f}, got {actual}"
    )


def assert_whole_minutes(actual: Any, expected: int, label: str = "minutes") -> None:
    """Assert a whole-minute integer figure (PRD 2.6)."""
    assert actual is not None, f"{label} must not be null"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label} should be {expected}, got {actual}"


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Assert a whole-cent money figure (PRD 2.6, PRD 3.7)."""
    assert actual is not None, f"{label} must not be null"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label} should be {expected}, got {actual}"


def assert_is_null(actual: Any, label: str) -> None:
    assert actual is None, f"{label} should be null, got {actual!r}"


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


def _parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert actual is not None, f"{label} must not be null"
    assert _parse_instant(str(actual)) == _parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_three_fractional_digits(actual: Any, label: str = "timestamp") -> None:
    """Assert an ISO 8601 UTC timestamp rendered with exactly three fractional digits."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert actual.endswith("Z"), f"{label} must be UTC with a trailing Z, got {actual}"
    assert "." in actual, f"{label} must carry fractional digits, got {actual}"
    fraction = actual.split(".")[-1][:-1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"{label} must carry exactly three fractional digits, got {actual}"
    )


def assert_business_date(actual: Any, expected: str, label: str = "business_date") -> None:
    """Assert a plain calendar date in YYYY-MM-DD form (PRD 2.4)."""
    assert actual == expected, f"{label} should be {expected}, got {actual!r}"


# --------------------------------------------------------------------------
# Envelope / identity
# --------------------------------------------------------------------------


def assert_request_id(meta: dict) -> None:
    """Assert `meta.api_request_id` starts with `req_` (PRD 2.2)."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )


def assert_no_update_tracking_fields(payload: dict, label: str = "inspection") -> None:
    """Assert `updated_at`/`version` are absent, as PRD 2.4 requires of an Inspection."""
    assert "updated_at" not in payload, (
        f"{label} must not carry updated_at; got {payload.get('updated_at')!r}"
    )
    assert "version" not in payload, (
        f"{label} must not carry version; got {payload.get('version')!r}"
    )


def assert_has_common_fields(payload: dict, label: str = "resource") -> None:
    """Assert the four common resource properties of PRD 2.4 are present."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in payload, f"{label} must carry {field}"


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------


def assert_linen_identity(linen: dict) -> None:
    """Assert `on_hand_clean + in_laundry + soiled_queue == total_owned_sets` (PRD 2.11)."""
    total = linen["on_hand_clean"] + linen["in_laundry"] + linen["soiled_queue"]
    assert total == linen["total_owned_sets"], (
        "linen ledger identity broken: "
        f"on_hand_clean={linen['on_hand_clean']} + in_laundry={linen['in_laundry']} "
        f"+ soiled_queue={linen['soiled_queue']} = {total} "
        f"!= total_owned_sets={linen['total_owned_sets']}"
    )


def assert_linen_buckets(
    linen: dict, on_hand_clean: int, in_laundry: int, soiled_queue: int
) -> None:
    """Assert the three linen buckets and re-check the ledger identity."""
    assert linen["on_hand_clean"] == on_hand_clean, (
        f"on_hand_clean should be {on_hand_clean}, got {linen['on_hand_clean']}"
    )
    assert linen["in_laundry"] == in_laundry, (
        f"in_laundry should be {in_laundry}, got {linen['in_laundry']}"
    )
    assert linen["soiled_queue"] == soiled_queue, (
        f"soiled_queue should be {soiled_queue}, got {linen['soiled_queue']}"
    )
    assert_linen_identity(linen)


def assert_roster_dimensions(
    roster: dict,
    status: Optional[str] = None,
    compliance_state: Optional[str] = None,
    waiver_state: Optional[str] = None,
) -> None:
    """Assert the three independent roster state dimensions of PRD 2.8."""
    if status is not None:
        assert roster["status"] == status, (
            f"roster status should be {status}, got {roster['status']}"
        )
    if compliance_state is not None:
        assert roster["compliance_state"] == compliance_state, (
            f"roster compliance_state should be {compliance_state}, "
            f"got {roster['compliance_state']}"
        )
    if waiver_state is not None:
        assert roster["waiver_state"] == waiver_state, (
            f"roster waiver_state should be {waiver_state}, got {roster['waiver_state']}"
        )


def assert_roster_totals(
    roster: dict,
    assigned_credits: Optional[float] = None,
    assigned_square_feet: Optional[int] = None,
) -> None:
    """Assert the roster's two ordinance running totals (PRD 2.8)."""
    if assigned_credits is not None:
        assert_credits(roster["assigned_credits"], assigned_credits, "assigned_credits")
    if assigned_square_feet is not None:
        assert roster["assigned_square_feet"] == assigned_square_feet, (
            f"assigned_square_feet should be {assigned_square_feet}, "
            f"got {roster['assigned_square_feet']}"
        )


def assert_ids_in_order(actual: Iterable[str], expected: Iterable[str], label: str) -> None:
    """Assert an ordered list of identifiers matches exactly, order included."""
    actual_list = list(actual)
    expected_list = list(expected)
    assert actual_list == expected_list, (
        f"{label} should be {expected_list} in that exact order, got {actual_list}"
    )
