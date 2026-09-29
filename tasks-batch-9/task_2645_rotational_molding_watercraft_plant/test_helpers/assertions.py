"""Domain assertions for the rules PRD.md states, plus the arithmetic they need.

Two habits are enforced here rather than left to each test:

* no float comparisons. Every numeric check converts through ``Decimal`` and
  quantises with ROUND_HALF_UP at the scale PRD.md section 2.4 declares for
  that field family.
* no ad hoc instant maths. PRD.md section 2.9 fixes the oven and cooling window
  projections and floors every elapsed duration, so the helpers below build the
  expected instants instead of hand-writing strings.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

from .constants import (
    MIN_MEASUREMENT_POINTS,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    WARPAGE_INDEX_CEILING,
    WARPAGE_INDEX_FLOOR,
)

# ----------------------------------------------------------------------
# Decimal plumbing
# ----------------------------------------------------------------------


def dec(value: Any) -> Decimal:
    """Convert a JSON number, numeric string or Decimal to an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Any, quantum: Decimal) -> Decimal:
    """Round ``value`` to ``quantum`` using the half-up rule of PRD.md section 2.4."""
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_to(value: Any, quantum: Decimal = Decimal("1")) -> Decimal:
    """Truncate ``value`` toward zero, the rounding PRD.md uses for floors."""
    return dec(value).quantize(quantum, rounding=ROUND_DOWN)


def assert_decimal_equals(
    actual: Any, expected: Any, quantum: Decimal, label: str = "value"
) -> None:
    """Assert two numbers agree once both are rounded half-up to ``quantum``."""
    got = round_half_up(actual, quantum)
    want = round_half_up(expected, quantum)
    assert got == want, f"{label}: expected {want}, got {got} (raw {actual!r})"


def assert_money_equals(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field equals ``expected``.

    PRD.md section 2.4 holds every money field as an integer count of cents, so
    the actual value must be an integer and not a rounded decimal.
    """
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def decimal_places(value: Any) -> int:
    """Return how many digits ``value`` carries after the decimal point."""
    text = format(dec(value), "f")
    return len(text.split(".")[1]) if "." in text else 0


def assert_at_most_scale(value: Any, places: int, label: str = "value") -> None:
    """Assert ``value`` carries no more decimal places than PRD.md declares."""
    got = decimal_places(value)
    assert got <= places, (
        f"{label}: PRD.md declares at most {places} decimals, got {got} ({value!r})"
    )


def assert_percent(value: Any, label: str = "percentage") -> None:
    """Assert a percentage sits in 0.00 to 100.00 at two decimals."""
    amount = dec(value)
    assert Decimal("0") <= amount <= Decimal("100"), (
        f"{label}: expected 0.00 to 100.00, got {amount}"
    )
    assert_at_most_scale(value, 2, label)


# ----------------------------------------------------------------------
# Instant arithmetic (PRD.md section 2.9)
# ----------------------------------------------------------------------


def parse_utc(instant: str) -> datetime:
    """Parse an ISO 8601 UTC instant with a trailing Z."""
    return datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def format_utc(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with a trailing Z."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_minutes(instant: str, minutes: int) -> str:
    """Return ``instant`` advanced by ``minutes`` whole minutes."""
    return format_utc(parse_utc(instant) + timedelta(minutes=minutes))


def shift_days(instant: str, days: int) -> str:
    """Return ``instant`` advanced by ``days`` whole days."""
    return format_utc(parse_utc(instant) + timedelta(days=days))


def elapsed_minutes_floor(start: str, end: str) -> int:
    """Whole minutes between two instants, floored as PRD.md section 2.9 requires."""
    delta = parse_utc(end) - parse_utc(start)
    return int(delta.total_seconds() // 60)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert parse_utc(str(actual)) == parse_utc(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ----------------------------------------------------------------------
# Entity shape
# ----------------------------------------------------------------------


def assert_common_fields(entity: dict[str, Any], label: str = "entity") -> None:
    """Assert the four fields PRD.md section 2.4 puts on every row are present.

    Every resource in this API carries ``id``, ``created_at``, ``updated_at``
    and ``version``; none of the sixteen is append-only.
    """
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{label}: missing common field {field}"
    assert isinstance(entity["version"], int), (
        f"{label}: version must be an integer, got {entity['version']!r}"
    )
    assert entity["version"] >= 1, f"{label}: version starts at 1"


def assert_version_unchanged(
    before: dict[str, Any], after: dict[str, Any], label: str = "entity"
) -> None:
    """Assert a refused write left the row's version untouched."""
    assert before["version"] == after["version"], (
        f"{label}: version moved from {before['version']} to {after['version']} "
        "on a request that should have persisted nothing"
    )


def assert_unchanged(
    before: dict[str, Any], after: dict[str, Any], fields: list[str], label: str = "entity"
) -> None:
    """Assert none of ``fields`` moved between two reads of the same row."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{label}.{field}: expected {before.get(field)!r} to be unchanged, "
            f"got {after.get(field)!r}"
        )


def assert_null_fields(
    entity: dict[str, Any], fields: list[str], label: str = "entity"
) -> None:
    """Assert every named field is null, as PRD.md requires before it is set."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{label}.{field}: expected null, got {entity.get(field)!r}"
        )


def assert_pagination_meta(
    meta: dict[str, Any], expected_total: int, limit: int, offset: int
) -> None:
    """Assert the four pagination fields PRD.md section 2.3 declares.

    ``has_more`` is true exactly when the offset plus the rows returned is
    strictly less than ``total_count``.
    """
    assert meta["total_count"] == expected_total, (
        f"total_count: expected {expected_total}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    assert isinstance(meta["has_more"], bool), "has_more must be a boolean"


# ----------------------------------------------------------------------
# Ledger invariants (PRD.md section 2.10)
# ----------------------------------------------------------------------


def assert_resin_ledger_conserved(lot: dict[str, Any]) -> None:
    """Assert available_kg + reserved_kg + consumed_kg equals received_kg."""
    total = (
        dec(lot["available_kg"]) + dec(lot["reserved_kg"]) + dec(lot["consumed_kg"])
    )
    assert_decimal_equals(
        total, lot["received_kg"], Q_MASS, "resin ledger available + reserved + consumed"
    )
    for bucket in ("available_kg", "reserved_kg", "consumed_kg"):
        assert dec(lot[bucket]) >= 0, f"{bucket} must never go negative"


def assert_warranty_reserve_conserved(model: dict[str, Any]) -> None:
    """Assert warranty_reserve_cents + warranty_paid_cents equals the initial reserve."""
    total = model["warranty_reserve_cents"] + model["warranty_paid_cents"]
    assert total == model["initial_warranty_reserve_cents"], (
        "warranty ledger: reserve "
        f"{model['warranty_reserve_cents']} + paid {model['warranty_paid_cents']} "
        f"!= initial {model['initial_warranty_reserve_cents']}"
    )
    assert model["warranty_reserve_cents"] >= 0, "reserve must never go negative"
    assert model["warranty_paid_cents"] >= 0, "paid must never go negative"


# ----------------------------------------------------------------------
# Cycle windows and elapsed time (PRD.md sections 2.9, 3.3)
# ----------------------------------------------------------------------


def assert_cycle_window_projection(cycle: dict[str, Any]) -> None:
    """Assert the three projected window stamps follow from the scheduled minutes.

    ``oven_end_at`` is ``oven_start_at`` advanced by ``scheduled_oven_minutes``,
    ``cooling_window_start_at`` equals ``oven_end_at``, and
    ``cooling_window_end_at`` is that advanced by ``scheduled_cooling_minutes``.
    """
    expected_oven_end = shift_minutes(
        cycle["oven_start_at"], cycle["scheduled_oven_minutes"]
    )
    assert_instant_equals(cycle["oven_end_at"], expected_oven_end, "oven_end_at")
    assert_instant_equals(
        cycle["cooling_window_start_at"], expected_oven_end, "cooling_window_start_at"
    )
    assert_instant_equals(
        cycle["cooling_window_end_at"],
        shift_minutes(expected_oven_end, cycle["scheduled_cooling_minutes"]),
        "cooling_window_end_at",
    )


def assert_elapsed_minutes_floored(
    cycle: dict[str, Any], field: str, start_field: str, end_field: str
) -> None:
    """Assert an elapsed-minute field is the floored difference of two stamps."""
    expected = elapsed_minutes_floor(cycle[start_field], cycle[end_field])
    assert cycle[field] == expected, (
        f"{field}: expected the floored {expected} minutes between "
        f"{start_field} and {end_field}, got {cycle[field]}"
    )


def assert_warpage_index_shape(value: Any, label: str = "warpage index") -> None:
    """Assert a warpage index is three decimals clamped to 0.000 through 5.000."""
    amount = dec(value)
    assert WARPAGE_INDEX_FLOOR <= amount <= WARPAGE_INDEX_CEILING, (
        f"{label}: expected {WARPAGE_INDEX_FLOOR} to {WARPAGE_INDEX_CEILING}, "
        f"got {amount}"
    )
    assert_at_most_scale(value, 3, label)


# ----------------------------------------------------------------------
# Inspection statistics (PRD.md section 3.6)
# ----------------------------------------------------------------------


def expected_wall_statistics(points: list[float]) -> dict[str, Decimal]:
    """Return the wall statistics PRD.md derives from a set of readings.

    The mean and the standard deviation are rounded to three decimals, the
    standard deviation divides by the number of points rather than by one less,
    and the coefficient of variation is the rounded deviation over the rounded
    mean expressed as a percentage at two decimals. Each intermediate is
    rounded before it is reused.
    """
    values = [dec(p) for p in points]
    count = Decimal(len(values))
    mean = round_half_up(sum(values) / count, Q_MASS)
    variance = sum((v - mean) ** 2 for v in values) / count
    sd = round_half_up(Decimal(variance).sqrt(), Q_MASS)
    cv = round_half_up(sd / mean * Decimal("100"), Q_PERCENT) if mean else Decimal("0.00")
    return {
        "mean_wall_thickness_mm": mean,
        "wall_sd_mm": sd,
        "wall_cv_pct": cv,
        "min_wall_thickness_mm": min(values),
    }


def assert_wall_statistics(unit: dict[str, Any], points: list[float]) -> None:
    """Assert a hull's wall statistics match the readings it was inspected with."""
    assert len(points) >= MIN_MEASUREMENT_POINTS, (
        f"PRD.md requires at least {MIN_MEASUREMENT_POINTS} readings"
    )
    expected = expected_wall_statistics(points)
    assert_decimal_equals(
        unit["mean_wall_thickness_mm"],
        expected["mean_wall_thickness_mm"],
        Q_MASS,
        "mean_wall_thickness_mm",
    )
    assert_decimal_equals(
        unit["wall_sd_mm"], expected["wall_sd_mm"], Q_MASS, "wall_sd_mm"
    )
    assert_decimal_equals(
        unit["wall_cv_pct"], expected["wall_cv_pct"], Q_PERCENT, "wall_cv_pct"
    )


def assert_hull_serial_format(
    hull_serial: str, order_code: str, cavity_index: int
) -> None:
    """Assert a hull serial follows the deterministic format PRD.md declares.

    The serial is the order code, the two-digit cavity index and a four-digit
    build sequence, joined by hyphens, and is never derived from the row id.
    """
    assert hull_serial.startswith(f"{order_code}-"), (
        f"hull_serial {hull_serial!r} must begin with the order code {order_code!r}"
    )
    tail = hull_serial[len(order_code) + 1 :]
    parts = tail.split("-")
    assert len(parts) == 2, f"hull_serial {hull_serial!r} must end in two segments"
    assert parts[0] == f"{cavity_index:02d}", (
        f"hull_serial {hull_serial!r} must carry cavity index {cavity_index:02d}"
    )
    assert len(parts[1]) == 4 and parts[1].isdigit(), (
        f"hull_serial {hull_serial!r} must end in a four-digit build sequence"
    )


# ----------------------------------------------------------------------
# Warehouse footprint and freight projections (PRD.md sections 3.7, 3.8)
# ----------------------------------------------------------------------


def assert_footprint_summary_consistent(summary: dict[str, Any]) -> None:
    """Assert the footprint projection agrees with itself.

    Committed plus remaining cube equals the site capacity, the utilisation is
    the committed share of capacity at two decimals, and the zone rows add up
    to the site totals.
    """
    capacity = dec(summary["footprint_capacity_cube_m3"])
    committed = dec(summary["committed_cube_m3"])
    remaining = dec(summary["remaining_cube_m3"])
    assert_decimal_equals(
        committed + remaining, capacity, Q_CUBE, "committed + remaining cube"
    )
    if capacity:
        assert_decimal_equals(
            summary["utilization_pct"],
            committed / capacity * Decimal("100"),
            Q_PERCENT,
            "utilization_pct",
        )
    zone_committed = sum(dec(z["committed_cube_m3"]) for z in summary["zones"])
    zone_capacity = sum(dec(z["capacity_cube_m3"]) for z in summary["zones"])
    assert_decimal_equals(zone_committed, committed, Q_CUBE, "sum of zone committed cube")
    assert_decimal_equals(zone_capacity, capacity, Q_CUBE, "sum of zone capacities")


def assert_posture_for_utilization(
    posture: str,
    utilization_pct: Any,
    restricted_threshold_pct: Any,
    frozen_threshold_pct: Any,
) -> None:
    """Assert the posture PRD.md selects for a utilisation.

    Both thresholds trigger at or above their value, and the frozen threshold is
    tested before the restricted one.
    """
    used = dec(utilization_pct)
    if used >= dec(frozen_threshold_pct):
        expected = "FROZEN"
    elif used >= dec(restricted_threshold_pct):
        expected = "RESTRICTED"
    else:
        expected = "NORMAL"
    assert posture == expected, (
        f"posture: {used} percent utilisation should be {expected}, got {posture}"
    )


def assert_freight_summary_consistent(summary: dict[str, Any]) -> None:
    """Assert the freight projection agrees with itself.

    The gross and nested cube totals are the sums of their line values, the
    cube utilisation is the nested share of trailer capacity, and the per-line
    freight amounts add up to the pre-discount total on the nested basis.
    """
    lines = summary["lines"]
    assert_decimal_equals(
        sum(dec(line["line_gross_cube_m3"]) for line in lines),
        summary["loaded_cube_m3"],
        Q_CUBE,
        "sum of line_gross_cube_m3",
    )
    assert_decimal_equals(
        sum(dec(line["line_nested_cube_m3"]) for line in lines),
        summary["nested_cube_m3"],
        Q_CUBE,
        "sum of line_nested_cube_m3",
    )
    assert summary["loaded_line_count"] == len(lines), (
        f"loaded_line_count {summary['loaded_line_count']} does not match "
        f"{len(lines)} line rows"
    )


def assert_claim_payout_arithmetic(claim: dict[str, Any]) -> None:
    """Assert a claim's four money fields agree with one another.

    The net payout is the gross less the storage deduction less the admin fee,
    and none of the four may be negative.
    """
    for field in (
        "pre_fee_gross_cents",
        "storage_deduction_cents",
        "admin_fee_cents",
        "net_payout_cents",
    ):
        assert claim[field] is not None, f"{field} must be set once a claim is priced"
        assert claim[field] >= 0, f"{field} must not be negative"
    expected = (
        claim["pre_fee_gross_cents"]
        - claim["storage_deduction_cents"]
        - claim["admin_fee_cents"]
    )
    assert_money_equals(claim["net_payout_cents"], expected, "net_payout_cents")
