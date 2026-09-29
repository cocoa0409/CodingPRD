"""Domain assertions for the EMD protocol QA API."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ALS_LEVELS,
    BYSTANDER_WEIGHTS,
    COMPRESSION_LIMIT_SEC,
    COMPRESSION_SPAN_SEC,
    COMPRESSION_FLOOR_SEC,
    COMPRESSIONS_COACHED_POINTS,
    HOT_LEVELS,
    INSTRUCTION_DELIVERED_POINTS,
    LATE_COMPRESSION_CAP,
    PRIORITY_RANK_BY_LEVEL,
    RECOGNITION_SPAN_SEC,
    SOLO_WEIGHTS,
)

# --------------------------------------------------------------- timestamps
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """Compare two ISO 8601 instants regardless of fractional-second rendering."""
    assert actual is not None, f"expected instant {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_utc_millisecond_timestamp(value: str) -> None:
    """The PRD renders created_at/updated_at in UTC with three fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp must be rendered in UTC with a Z suffix: {value!r}"
    fractional = value[:-1].split(".")
    assert len(fractional) == 2 and len(fractional[1]) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def plus_days(instant: str, days: int) -> str:
    """The instant shifted by whole days, rendered the way the API accepts it."""
    shifted = parse_instant(instant) + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_minutes(instant: str, minutes: int) -> str:
    shifted = parse_instant(instant) + timedelta(minutes=minutes)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------- common fields
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """id is a server-minted UUID; created_at/updated_at are UTC; version starts at 1."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID: {row['id']!r}"
    assert_utc_millisecond_timestamp(row["created_at"])
    assert_utc_millisecond_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_score_sheet_shape(sheet: Dict[str, Any]) -> None:
    """The score sheet is immutable, so it carries only id and created_at."""
    assert is_valid_uuid(sheet["id"]), f"id must be a UUID: {sheet['id']!r}"
    assert_utc_millisecond_timestamp(sheet["created_at"])
    assert "updated_at" not in sheet, "an immutable score sheet must not carry updated_at"
    assert "version" not in sheet, "an immutable score sheet must not carry version"


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """meta.api_request_id is a fresh identifier prefixed with req_."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {meta['api_request_id']!r}"
    )


# ------------------------------------------------------------------ numbers
def approx1(expected: float):
    """Comparison tolerance for a value the PRD rounds to one decimal place."""
    return pytest.approx(expected, abs=0.01)


def approx2(expected: float):
    """Comparison tolerance for a value the PRD rounds to two decimal places."""
    return pytest.approx(expected, abs=0.001)


def assert_decimal_places(value: float, places: int) -> None:
    """The rendered value carries no more precision than the PRD allows."""
    assert value is not None
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{value} carries more than {places} decimal places"
    )


def round_half_up(value: float, places: int) -> float:
    """The PRD's rounding rule: half away from zero at the given precision."""
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# ------------------------------------------------- determinant code decoding
def decode_determinant_code(code: str) -> Dict[str, Any]:
    """Decode a determinant code into its rank, response mode and resource level."""
    chief_complaint, level, sub = code.split("-")
    return {
        "priority_rank": PRIORITY_RANK_BY_LEVEL[level],
        "response_mode": "HOT" if level in HOT_LEVELS else "COLD",
        "resource": "ALS" if level in ALS_LEVELS else "BLS",
        "chief_complaint": int(chief_complaint),
        "sub_code": int(sub),
    }


def expected_dacpr_index(
    *,
    recognized: bool,
    recognition_time_sec: int,
    time_to_first_compression_sec: int,
    instructions_delivered: bool,
    compressions_coached: bool,
    bystander_cpr_in_progress: bool,
) -> float:
    """Reproduce the PRD's DA-CPR performance index from its declared constants."""
    if not recognized:
        return 0.0
    recognition_sub = 100.0 * max(0, RECOGNITION_SPAN_SEC - recognition_time_sec) / RECOGNITION_SPAN_SEC
    if time_to_first_compression_sec <= COMPRESSION_FLOOR_SEC:
        compression_sub = 100.0
    else:
        compression_sub = (
            100.0
            * max(0, COMPRESSION_LIMIT_SEC - time_to_first_compression_sec)
            / COMPRESSION_SPAN_SEC
        )
    instruction_sub = 0.0
    if instructions_delivered:
        instruction_sub += INSTRUCTION_DELIVERED_POINTS
    if compressions_coached:
        instruction_sub += COMPRESSIONS_COACHED_POINTS
    weights = BYSTANDER_WEIGHTS if bystander_cpr_in_progress else SOLO_WEIGHTS
    weighted = (
        weights["recognition"] * recognition_sub
        + weights["compression"] * compression_sub
        + weights["instruction"] * instruction_sub
    ) / 100.0
    index = round_half_up(weighted, 1)
    if time_to_first_compression_sec > COMPRESSION_LIMIT_SEC:
        index = min(index, LATE_COMPRESSION_CAP)
    return index


# ------------------------------------------------------------------- listing
def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_list_contains_exactly(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert sorted(ids_of(rows)) == sorted(expected_ids), (
        f"expected exactly {expected_ids}, got {ids_of(rows)}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """The default list order is created_at ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows must be ordered by created_at ascending"
