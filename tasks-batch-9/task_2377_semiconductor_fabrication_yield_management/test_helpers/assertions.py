"""Domain assertion helpers for the Semiconductor Fab Yield API.

Numeric helpers encode the PRD's three rounding scales (2, 3 and 4 decimal
places) so a test states the expected value once and the helper enforces both
equality and the declared precision.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing.assertions import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CYCLE_DP,
    MONEY_DP,
    RATIO_DP,
    TOL_2DP,
    TOL_3DP,
    TOL_4DP,
)


# --------------------------------------------------------------------------
# Rounding (PRD §2.5)
# --------------------------------------------------------------------------


def round_half_up(value: float, places: int) -> float:
    """Round ``value`` to ``places`` decimals, halves away from zero."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _assert_precision(value: float, places: int, field: str) -> None:
    assert value is not None, "%s must be present" % field
    rounded = round_half_up(float(value), places)
    assert abs(float(value) - rounded) < 1e-9, (
        "%s=%r is not rounded to %d decimal places" % (field, value, places)
    )


def assert_hours(actual: Any, expected: float, field: str = "hours") -> None:
    """An hours / score / measured value: two decimal places."""
    _assert_precision(actual, MONEY_DP, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_2DP), (
        "%s expected %r, got %r" % (field, expected, actual)
    )


def assert_days(actual: Any, expected: float, field: str = "days") -> None:
    """A cycle-time value in days: three decimal places."""
    _assert_precision(actual, CYCLE_DP, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_3DP), (
        "%s expected %r, got %r" % (field, expected, actual)
    )


def assert_ratio(actual: Any, expected: float, field: str = "ratio") -> None:
    """A yield, ratio or sigma deviation: four decimal places."""
    _assert_precision(actual, RATIO_DP, field)
    assert float(actual) == pytest.approx(expected, abs=TOL_4DP), (
        "%s expected %r, got %r" % (field, expected, actual)
    )


# --------------------------------------------------------------------------
# Common resource properties (PRD §2.4)
# --------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the four properties every entity but a measurement carries."""
    assert is_valid_uuid(entity["id"]), "id must be a bare UUID: %r" % entity["id"]
    assert "_" not in str(entity["id"]), "id must carry no prefix"
    assert is_iso8601_timestamp(entity["created_at"]), (
        "created_at must be ISO 8601 UTC: %r" % entity["created_at"]
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        "updated_at must be ISO 8601 UTC: %r" % entity["updated_at"]
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            "expected version %d, got %d" % (expected_version, entity["version"])
        )


def assert_measurement_common_fields(measurement: Dict[str, Any]) -> None:
    """A metrology reading carries only ``id`` and ``created_at`` (PRD §2.4)."""
    assert is_valid_uuid(measurement["id"])
    assert is_iso8601_timestamp(measurement["created_at"])
    assert "updated_at" not in measurement, (
        "a metrology measurement has no updated_at"
    )
    assert "version" not in measurement, "a metrology measurement has no version"


def assert_timestamp_equals(actual: Any, expected_instant: str, field: str = "timestamp") -> None:
    """Compare a response timestamp against a canonical instant.

    Tolerates the fractional-second form the PRD mandates on output while the
    expected instant may be written without it.
    """
    assert actual is not None, "%s must be present" % field
    assert is_iso8601_timestamp(actual), "%s must be ISO 8601: %r" % (field, actual)
    assert _normalise_instant(actual) == _normalise_instant(expected_instant), (
        "%s expected %s, got %s" % (field, expected_instant, actual)
    )


def _normalise_instant(value: str) -> str:
    text = str(value).replace("z", "Z")
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text:
        text = text.split("+")[0]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3].rstrip("0")
        text = head + ("." + frac if frac else "")
    return text + "Z"


# --------------------------------------------------------------------------
# Envelope (PRD §2.2)
# --------------------------------------------------------------------------


def assert_envelope(body: Dict[str, Any], expected_response_type: str) -> None:
    """Assert the three-key envelope and its request-tracking metadata."""
    assert set(["meta", "response_type", "data"]).issubset(body.keys())
    assert body["response_type"] == expected_response_type
    meta = body["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        "api_request_id must carry the req_ prefix: %r" % meta["api_request_id"]
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """Default ordering is ``created_at`` ascending (PRD §2.3)."""
    stamps = [_normalise_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), "rows must be ordered by created_at ascending"


# --------------------------------------------------------------------------
# Entity-shape assertions
# --------------------------------------------------------------------------


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of exact field values, reporting every mismatch."""
    mismatches = []
    for field, value in expected.items():
        actual = entity.get(field, "<missing>")
        if actual != value:
            mismatches.append("%s: expected %r, got %r" % (field, value, actual))
    assert not mismatches, "; ".join(mismatches)


def assert_nulls(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity.get(field, "<missing>") is None, (
            "%s must be null, got %r" % (field, entity.get(field))
        )


def assert_lot_state(
    lot: Dict[str, Any],
    flow_state: Optional[str] = None,
    hold_state: Optional[str] = None,
    current_step_seq: Optional[int] = None,
) -> None:
    if flow_state is not None:
        assert lot["flow_state"] == flow_state, (
            "flow_state expected %s, got %s" % (flow_state, lot["flow_state"])
        )
    if hold_state is not None:
        assert lot["hold_state"] == hold_state, (
            "hold_state expected %s, got %s" % (hold_state, lot["hold_state"])
        )
    if current_step_seq is not None:
        assert lot["current_step_seq"] == current_step_seq


def assert_wafer_conservation(lot: Dict[str, Any], *children: Dict[str, Any]) -> None:
    """Wafers are conserved across a split: parent + children == origin."""
    total = lot["wafer_count"] + sum(child["wafer_count"] for child in children)
    assert total == lot["origin_wafer_count"], (
        "wafer_count sum %d does not match origin_wafer_count %d"
        % (total, lot["origin_wafer_count"])
    )


def assert_ledger_restored(before: float, after: float) -> None:
    """An abort restores the reservation exactly (PRD §2.12)."""
    assert float(after) == pytest.approx(float(before), abs=TOL_2DP), (
        "capacity expected to return to %r, got %r" % (before, after)
    )
