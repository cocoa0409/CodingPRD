"""Domain assertions and the arithmetic the PRD pins.

The rounding helpers reimplement the PRD's stated method — "Wherever a
computation requires rounding, the method is **round half up**" — so a test can
state an expected figure as the formula the PRD gives rather than as a magic
number, and still fail loudly when the service rounds the other way.
"""

import datetime
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DEVIATION_SEVERITY_BANDS,
    FINDING_BASE_CENTS,
    HANDLING_TIERS,
    HACCP_FAIL_WEIGHT,
    HACCP_REWORK_WEIGHT,
    HACCP_RISK_SCORE_CAP,
    LATENESS_BANDS,
    OVERHEAD_RATE,
    SEVERITY_MULTIPLIER,
)

# ---------------------------------------------------------------------------
# Rounding primitives (PRD §2.8)
# ---------------------------------------------------------------------------


def half_up(value: Any, places: int = 0) -> Decimal:
    """Round half up: "a value exactly midway ... rounds away from zero"."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def half_up_int(value: Any) -> int:
    return int(half_up(value, 0))


def round_up_units(value: Any) -> int:
    """"Where a calculation distributes a passenger count into a unit count it
    likewise rounds **up**" (PRD §2.8)."""
    return int(math.ceil(Decimal(str(value))))


def ceil_minutes(seconds: float) -> int:
    """"Where a calculation converts a duration into whole minutes it rounds
    **up** to the next whole minute" (PRD §2.8)."""
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 60.0))


# ---------------------------------------------------------------------------
# Instant arithmetic on the logical clock's ISO 8601 UTC strings
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime.datetime:
    text = value.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(text)


def format_instant(moment: datetime.datetime) -> str:
    """Whole-second UTC rendering, the form the PRD uses for pinned instants."""
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_minutes(value: str, minutes: int) -> str:
    return format_instant(parse_instant(value) + datetime.timedelta(minutes=minutes))


def shift_hours(value: str, hours: int) -> str:
    return format_instant(parse_instant(value) + datetime.timedelta(hours=hours))


def shift_seconds(value: str, seconds: int) -> str:
    return format_instant(parse_instant(value) + datetime.timedelta(seconds=seconds))


def minutes_between(start: str, end: str) -> int:
    delta = (parse_instant(end) - parse_instant(start)).total_seconds()
    return ceil_minutes(delta)


def same_instant(left: str, right: str) -> bool:
    return parse_instant(left) == parse_instant(right)


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    assert actual is not None, "expected instant %s, got null" % expected
    assert same_instant(actual, expected), "expected instant %s, got %s" % (
        expected,
        actual,
    )


# ---------------------------------------------------------------------------
# Common resource shape (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """`id`, `created_at`, `updated_at` and `version` on a versioned resource."""
    assert is_valid_uuid(row["id"]), "id is not a bare UUID: %r" % (row.get("id"),)
    assert is_iso8601_timestamp(row["created_at"]), "bad created_at: %r" % (
        row.get("created_at"),
    )
    assert is_iso8601_timestamp(row["updated_at"]), "bad updated_at: %r" % (
        row.get("updated_at"),
    )
    assert isinstance(row["version"], int), "version is not an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, "expected version %s, got %s" % (
            expected_version,
            row["version"],
        )


def assert_immutable_record_fields(row: Dict[str, Any]) -> None:
    """The HACCP check shape: "both `updated_at` and `version` are absent from it
    entirely" (PRD §2.5)."""
    assert is_valid_uuid(row["id"]), "id is not a bare UUID: %r" % (row.get("id"),)
    assert is_iso8601_timestamp(row["created_at"]), "bad created_at: %r" % (
        row.get("created_at"),
    )
    assert "updated_at" not in row, "updated_at must be absent, got %r" % (
        row.get("updated_at"),
    )
    assert "version" not in row, "version must be absent, got %r" % (row.get("version"),)


def assert_error_envelope_shape(body: Dict[str, Any]) -> None:
    """"The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`" and `data` carries only `error_id` and `message`
    (PRD §2.2)."""
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError("id %s not present in collection" % row_id)


def find_by(rows: Iterable[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    for row in rows:
        if all(row.get(key) == value for key, value in fields.items()):
            return row
    raise AssertionError("no row matching %r in collection" % (fields,))


def maybe_find_by(rows: Iterable[Dict[str, Any]], **fields: Any):
    for row in rows:
        if all(row.get(key) == value for key, value in fields.items()):
            return row
    return None


def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    """"`total_count` counts every row matching the supplied filters before
    paging" (PRD §2.3)."""
    assert meta["total_count"] == expected, "expected total_count %s, got %s" % (
        expected,
        meta["total_count"],
    )


def assert_ordered_by(rows: Sequence[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), "collection is not ascending by %s: %r" % (
        field,
        values,
    )


# ---------------------------------------------------------------------------
# Cart state axes (PRD §2.9)
# ---------------------------------------------------------------------------


def assert_cart_axes(cart: Dict[str, Any], build_status: str, seal_status: str) -> None:
    """The cart's "two independent state axes on the same row"."""
    assert cart["build_status"] == build_status, "expected build_status %s, got %s" % (
        build_status,
        cart["build_status"],
    )
    assert cart["seal_status"] == seal_status, "expected seal_status %s, got %s" % (
        seal_status,
        cart["seal_status"],
    )


def assert_flight_ledger(
    flight: Dict[str, Any],
    units_produced: Optional[int] = None,
    units_loaded: Optional[int] = None,
    units_scrapped: Optional[int] = None,
    unit_balance: Optional[int] = None,
) -> None:
    """The conserved unit counters of PRD §2.9."""
    if units_produced is not None:
        assert flight["units_produced"] == units_produced
    if units_loaded is not None:
        assert flight["units_loaded"] == units_loaded
    if units_scrapped is not None:
        assert flight["units_scrapped"] == units_scrapped
    if unit_balance is not None:
        assert flight["unit_balance"] == unit_balance
    assert flight["unit_balance"] == flight["units_produced"] - flight["units_loaded"], (
        "unit_balance must be units_produced minus units_loaded, got %s vs %s - %s"
        % (flight["unit_balance"], flight["units_produced"], flight["units_loaded"])
    )


# ---------------------------------------------------------------------------
# Money arithmetic (PRD §3.9)
# ---------------------------------------------------------------------------


def item_gross_cents(qty_units: int, unit_cost_cents: int) -> int:
    """"`qty_units` multiplied by its specification's `unit_cost_cents`,
    multiplied by one plus a twelve percent overhead rate, with that product
    rounded half up to whole cents"."""
    raw = Decimal(qty_units) * Decimal(unit_cost_cents) * (
        Decimal(1) + Decimal(str(OVERHEAD_RATE))
    )
    return int(half_up(raw, 0))


def handling_rate(net_cost_cents: int) -> Decimal:
    """The band containing `net_cost_cents` (PRD §3.9)."""
    for low, high, rate in HANDLING_TIERS:
        if net_cost_cents >= low and (high is None or net_cost_cents <= high):
            return Decimal(str(rate))
    raise AssertionError("no handling band contains %s" % net_cost_cents)


def handling_fee_cents(net_cost_cents: int) -> int:
    return int(half_up(Decimal(net_cost_cents) * handling_rate(net_cost_cents), 0))


def blended_unit_rate_cents(gross_cost_cents: int, uplifted_units: int) -> int:
    """"`gross_cost_cents` divided by `uplifted_units`, rounded half up to whole
    cents — and rounded exactly once, not per line"."""
    return int(half_up(Decimal(gross_cost_cents) / Decimal(uplifted_units), 0))


def recovery_credit_cents(
    credit_basis_units: int, blended_rate_cents: int, recovery_rate_pct: Any
) -> int:
    raw = (
        Decimal(credit_basis_units)
        * Decimal(blended_rate_cents)
        * Decimal(str(recovery_rate_pct))
        / Decimal(100)
    )
    return int(half_up(raw, 0))


def cabin_cost_per_pax_cents(cabin_cost_cents: int, cabin_pax: int) -> int:
    """The first rounding of the pinned four-step blend (PRD §3.9)."""
    return int(half_up(Decimal(cabin_cost_cents) / Decimal(cabin_pax), 0))


def blended_cost_per_pax_cents(cabin_figures: Sequence[Any], total_pax: int) -> int:
    """The second and final rounding: each included cabin's rounded per-passenger
    cost multiplied by that cabin's passenger count, summed, divided by
    `total_pax`, rounded half up (PRD §3.9)."""
    numerator = Decimal(0)
    for rounded_per_pax, cabin_pax in cabin_figures:
        numerator += Decimal(rounded_per_pax) * Decimal(cabin_pax)
    return int(half_up(numerator / Decimal(total_pax), 0))


def lateness_penalty_cents(billable_minutes: int) -> int:
    """The three marginal bands of PRD §3.7, each pricing "only the minutes that
    fall inside it"."""
    remaining = max(0, billable_minutes)
    total = 0
    for width, rate in LATENESS_BANDS:
        if remaining <= 0:
            break
        take = remaining if width == 0 else min(width, remaining)
        total += take * rate
        remaining -= take
    return total


def finding_penalty_cents(finding_type: str, severity: str) -> int:
    """"`penalty_cents` is the base multiplied by the multiplier, rounded half up
    to whole cents" (PRD §3.10)."""
    raw = Decimal(FINDING_BASE_CENTS[finding_type]) * Decimal(
        str(SEVERITY_MULTIPLIER[severity])
    )
    return int(half_up(raw, 0))


def deviation_severity(deviation_pct: Any):
    """The inclusive-lower-bound bands of PRD §3.9."""
    value = Decimal(str(deviation_pct))
    for threshold, severity in DEVIATION_SEVERITY_BANDS:
        if value >= Decimal(str(threshold)):
            return severity
    return None


def spec_deviation_pct(delivered: int, required: int) -> Decimal:
    """"the absolute difference between delivered and required, divided by
    required, multiplied by one hundred, and rounded half up to two decimals"."""
    raw = Decimal(abs(delivered - required)) / Decimal(required) * Decimal(100)
    return half_up(raw, 2)


def haccp_risk_score(fail_count: int, rework_rounds: int) -> Decimal:
    """"weighting each failed check on the batch at 40.00 and each completed
    rework round at 15.00", clamped at 100.00 (PRD §3.5)."""
    raw = Decimal(fail_count) * Decimal(str(HACCP_FAIL_WEIGHT)) + Decimal(
        rework_rounds
    ) * Decimal(str(HACCP_REWORK_WEIGHT))
    return min(Decimal(str(HACCP_RISK_SCORE_CAP)), half_up(raw, 2))


# ---------------------------------------------------------------------------
# Decimal-valued response fields
# ---------------------------------------------------------------------------


def assert_decimal_equals(actual: Any, expected: Any, places: int = 2) -> None:
    """Percentages and risk scores are "carried to exactly two decimal places"."""
    assert half_up(actual, places) == half_up(expected, places), (
        "expected %s, got %s" % (expected, actual)
    )
