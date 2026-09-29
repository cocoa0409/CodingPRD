"""Domain assertion helpers shared across the suite."""

import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Numeric helpers mirroring the documented rounding discipline
# ---------------------------------------------------------------------------
def round_half_up(value, places: int = 2):
    """Round away from zero at the midpoint, as the money rules require."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(result) if places > 0 else int(result)


def round_half_up_cents(value) -> int:
    """Round a fractional cent amount half-up to a whole number of cents."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def assert_money_equals(actual, expected, label: str = "amount") -> None:
    """Cent amounts are integers; compare them exactly."""
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_score_equals(actual, expected, label: str = "score") -> None:
    """Scores are carried to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct_equals(actual, expected, label: str = "percentage") -> None:
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common field families
# ---------------------------------------------------------------------------
MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON_FIELDS = ("id", "created_at")


def assert_mutable_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """A mutable row carries id, created_at, updated_at and version."""
    for name in MUTABLE_COMMON_FIELDS:
        assert name in entity, f"{label} is missing '{name}'"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at must be an ISO-8601 timestamp"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label}.updated_at must be an ISO-8601 timestamp"
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_immutable_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """An immutable row carries only id and created_at."""
    for name in IMMUTABLE_COMMON_FIELDS:
        assert name in entity, f"{label} is missing '{name}'"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at must be an ISO-8601 timestamp"
    )
    assert "updated_at" not in entity, f"{label} must not expose 'updated_at'"
    assert "version" not in entity, f"{label} must not expose 'version'"


def assert_fields_present(entity: Dict[str, Any], names: Iterable[str], label: str) -> None:
    missing = [n for n in names if n not in entity]
    assert not missing, f"{label} is missing fields: {missing}"


# ---------------------------------------------------------------------------
# Date arithmetic mirroring the documented derivations
# ---------------------------------------------------------------------------
def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def iso(value: date) -> str:
    return value.isoformat()


def shift_days(value: str, days: int) -> str:
    return iso(parse_date(value) + timedelta(days=days))


def expected_session_end(start: str, weeks: int) -> str:
    """The final day of a session that runs ``weeks`` whole weeks from start."""
    return shift_days(start, weeks * 7 - 1)


def inclusive_days(start: str, end: str) -> int:
    return (parse_date(end) - parse_date(start)).days + 1


def weeks_ceil_from_days(days: int) -> int:
    return math.ceil(days / 7)


# ---------------------------------------------------------------------------
# Stipend derivations
# ---------------------------------------------------------------------------
def expected_period_count(weeks: int) -> int:
    return math.ceil(weeks / 2)


def expected_period_split(
    start_date: str, session_end_date: str, weeks: int, weekly_rate_cents: int
) -> List[Dict[str, Any]]:
    """The full expected disbursement row skeleton for a scheduled session."""
    rows: List[Dict[str, Any]] = []
    count = expected_period_count(weeks)
    for index in range(1, count + 1):
        weeks_in_period = 2 if index < count else weeks - 2 * (count - 1)
        period_start = shift_days(start_date, 14 * (index - 1))
        period_end = min(shift_days(period_start, 13), session_end_date)
        rows.append(
            {
                "period_index": index,
                "weeks_in_period": weeks_in_period,
                "period_start_date": period_start,
                "period_end_date": period_end,
                "gross_cents": weekly_rate_cents * weeks_in_period,
            }
        )
    return rows


def expected_withholding_sequence(
    gross_amounts: List[int], rate: float, exemption_cents: int = 60000
) -> List[Dict[str, int]]:
    """Per-payment taxable slice, withholding and net under the running exemption."""
    out: List[Dict[str, int]] = []
    cumulative_before = 0
    for gross in gross_amounts:
        cumulative_after = cumulative_before + gross
        excess_before = max(0, cumulative_before - exemption_cents)
        excess_after = max(0, cumulative_after - exemption_cents)
        taxable = excess_after - excess_before
        withheld = round_half_up_cents(taxable * Decimal(str(rate)))
        out.append(
            {
                "gross_cents": gross,
                "cumulative_taxable_cents": taxable,
                "withholding_cents": withheld,
                "net_cents": gross - withheld,
            }
        )
        cumulative_before = cumulative_after
    return out


# ---------------------------------------------------------------------------
# Ledger assertions
# ---------------------------------------------------------------------------
def assert_cycle_stipend_ledger(
    cycle: Dict[str, Any], committed: int, uncommitted: int
) -> None:
    assert_money_equals(
        cycle["stipend_committed_cents"], committed, "cycle.stipend_committed_cents"
    )
    assert_money_equals(
        cycle["stipend_uncommitted_cents"], uncommitted, "cycle.stipend_uncommitted_cents"
    )


def assert_cycle_slot_ledger(cycle: Dict[str, Any], filled: int, open_slots: int) -> None:
    assert cycle["slots_filled_count"] == filled, (
        f"cycle.slots_filled_count: expected {filled}, got {cycle['slots_filled_count']}"
    )
    assert cycle["slots_open_count"] == open_slots, (
        f"cycle.slots_open_count: expected {open_slots}, got {cycle['slots_open_count']}"
    )


def assert_studio_day_ledger(
    studio: Dict[str, Any], reserved_days: int, active_count: int
) -> None:
    assert studio["reserved_resident_days"] == reserved_days, (
        "studio.reserved_resident_days: expected "
        f"{reserved_days}, got {studio['reserved_resident_days']}"
    )
    assert studio["active_assignment_count"] == active_count, (
        "studio.active_assignment_count: expected "
        f"{active_count}, got {studio['active_assignment_count']}"
    )


def assert_housing_bed_night_ledger(unit: Dict[str, Any], bed_nights: int) -> None:
    assert unit["occupied_bed_nights"] == bed_nights, (
        "housing_unit.occupied_bed_nights: expected "
        f"{bed_nights}, got {unit['occupied_bed_nights']}"
    )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def find_by(rows: List[Dict[str, Any]], **criteria) -> Optional[Dict[str, Any]]:
    for row in rows:
        if all(row.get(k) == v for k, v in criteria.items()):
            return row
    return None


def require_by(rows: List[Dict[str, Any]], **criteria) -> Dict[str, Any]:
    found = find_by(rows, **criteria)
    assert found is not None, f"no row matching {criteria} among {len(rows)} rows"
    return found


def sorted_by(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: r[key])


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in rows]


def assert_ascending_by_created_at(rows: List[Dict[str, Any]]) -> None:
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), "rows must be ordered by ascending created_at"
