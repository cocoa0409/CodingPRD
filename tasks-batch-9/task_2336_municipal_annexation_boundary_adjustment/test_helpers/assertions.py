"""Domain assertion helpers and reference arithmetic.

The reference arithmetic mirrors the rounding discipline the PRD pins: money is
rounded half up to a whole cent, percentages and index scores to two decimals,
and the three named ratios to four decimals. Everything uses `Decimal` so the
half-up boundary cases are exact rather than binary-float approximations.
"""
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C


# ==========================================================================
# Rounding primitives
# ==========================================================================
def round_half_up(value, places: int = 0):
    """Round half up to `places` decimal places, returning an int when
    `places` is 0 and a `Decimal` otherwise."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else result


def cents(value) -> int:
    """Round a monetary quantity half up to a whole cent."""
    return round_half_up(value, 0)


def pct(value) -> Decimal:
    """Round a percentage or index score half up to two decimals."""
    return round_half_up(value, 2)


def ratio4(value) -> Decimal:
    """Round one of the three named ratios half up to four decimals."""
    return round_half_up(value, 4)


def acres(value) -> Decimal:
    """Round territory acreage half up to two decimals."""
    return round_half_up(value, 2)


def approx_equal(actual, expected, places: int = 2) -> bool:
    return round_half_up(actual, places) == round_half_up(expected, places)


# ==========================================================================
# Calendar helpers (the PRD counts whole calendar days, both endpoints)
# ==========================================================================
def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def inclusive_day_count(start: str, end: str) -> int:
    """Calendar days from `start` through `end` counting both endpoints, so a
    one-day window counts 1."""
    return (parse_date(end) - parse_date(start)).days + 1


def add_days(iso_instant: str, days: int) -> str:
    """Advance an ISO instant by whole days, preserving the time of day."""
    head = iso_instant[:10]
    tail = iso_instant[10:]
    return (parse_date(head) + timedelta(days=days)).isoformat() + tail


def fiscal_year_end(reference: str, fiscal_year_end_month_day: str) -> date:
    """The fiscal year end relative to `reference`: the statute's month and day
    in the reference's own year when the reference is on or before it, and the
    same month and day in the following year otherwise."""
    ref = parse_date(reference)
    month, day = (int(part) for part in fiscal_year_end_month_day.split("-"))
    candidate = date(ref.year, month, day)
    if ref <= candidate:
        return candidate
    return date(ref.year + 1, month, day)


def remaining_fiscal_days(reference: str, fiscal_year_end_month_day: str) -> int:
    """Days from `reference` through its fiscal year end, both endpoints
    counted."""
    fye = fiscal_year_end(reference, fiscal_year_end_month_day)
    return (fye - parse_date(reference)).days + 1


def next_quarter_start(reference: str) -> date:
    """The first day of the calendar quarter following the one containing
    `reference`."""
    ref = parse_date(reference)
    quarter = (ref.month - 1) // 3
    if quarter == 3:
        return date(ref.year + 1, 1, 1)
    return date(ref.year, quarter * 3 + 4, 1)


def remaining_quarters(reference: str) -> int:
    """Calendar quarters remaining including the one containing
    `reference`: four for January through March, one for October through
    December."""
    return C.QUARTERS_PER_YEAR - ((parse_date(reference).month - 1) // 3)


# ==========================================================================
# Reference implementations of the pinned calculations
# ==========================================================================
def expected_contiguity_ratio(shared_boundary_feet, corporate_boundary_perimeter_feet):
    return ratio4(
        Decimal(str(shared_boundary_feet)) / Decimal(str(corporate_boundary_perimeter_feet))
    )


def expected_developed_lot_ratio(developed_lot_count: int, total_lot_count: int):
    return ratio4(Decimal(developed_lot_count) / Decimal(max(total_lot_count, 1)))


def expected_density(dwelling_units: int, territory_acreage) -> Decimal:
    divisor = max(Decimal(str(territory_acreage)), Decimal("0.01"))
    return ratio4(Decimal(dwelling_units) / divisor)


def expected_qualification_index(
    contiguity_ratio,
    contiguity_min_ratio,
    urban_development_qualified: bool,
    density,
    urban_density_min_units_per_acre,
    developed_lot_ratio,
    subdivision_test_min_developed_ratio,
    max_service_distance_miles,
):
    """base + urban bonus - density penalty - distance penalty, capped at 100,
    floored at 0, rounded half up to two decimals."""
    ramp = Decimal(str(contiguity_min_ratio)) * C.CONTIGUITY_RAMP_MULTIPLE
    base = Decimal(100) * min(Decimal(1), Decimal(str(contiguity_ratio)) / ramp)

    bonus = Decimal(str(C.URBAN_BONUS)) if urban_development_qualified else Decimal(0)

    density_penalty = Decimal(0)
    if Decimal(str(density)) < Decimal(str(urban_density_min_units_per_acre)) and Decimal(
        str(developed_lot_ratio)
    ) < Decimal(str(subdivision_test_min_developed_ratio)):
        density_penalty = Decimal(str(C.DENSITY_PENALTY))

    excess = Decimal(str(max_service_distance_miles)) - Decimal(C.DISTANCE_FREE_MILES)
    whole_excess = excess.to_integral_value(rounding=ROUND_CEILING)
    if whole_excess < 0:
        whole_excess = Decimal(0)
    distance_penalty = whole_excess * Decimal(str(C.DISTANCE_PENALTY_PER_MILE))

    raw = base + bonus - density_penalty - distance_penalty
    raw = min(raw, Decimal(100))
    raw = max(raw, Decimal(0))
    return pct(raw)


def expected_overhead_tier_pct(base_service_cost_cents: int) -> float:
    """Selected from the cost *before* overhead is added."""
    if base_service_cost_cents < C.OVERHEAD_TIER_1_CEILING_CENTS:
        return C.OVERHEAD_TIER_1_PCT
    if base_service_cost_cents < C.OVERHEAD_TIER_2_CEILING_CENTS:
        return C.OVERHEAD_TIER_2_PCT
    return C.OVERHEAD_TIER_3_PCT


def expected_property_tax_cents(assessed_value_cents: int, general_fund_millage_rate) -> int:
    return cents(
        Decimal(assessed_value_cents) * Decimal(str(general_fund_millage_rate)) / Decimal(1000)
    )


def expected_average_cost_base_cents(
    citywide_annual_service_cost_cents: int,
    projected_population: int,
    citywide_population: int,
) -> int:
    return cents(
        Decimal(citywide_annual_service_cost_cents)
        * Decimal(projected_population)
        / Decimal(citywide_population)
    )


def expected_deficit_ratio_pct(net_annual_impact_cents: int, gross_annual_revenue_cents: int):
    if net_annual_impact_cents >= 0:
        return pct(0)
    if gross_annual_revenue_cents == 0:
        return pct(100)
    return pct(
        Decimal(abs(net_annual_impact_cents))
        * Decimal(100)
        / Decimal(gross_annual_revenue_cents)
    )


def expected_share_value_cents(assessed_value_cents: int, ownership_share_pct) -> int:
    """Each individual share is rounded to a whole cent *before* the shares are
    summed."""
    return cents(
        Decimal(assessed_value_cents) * Decimal(str(ownership_share_pct)) / Decimal(100)
    )


def expected_weight_pct(numerator: int, denominator: int):
    if denominator == 0:
        return pct(0)
    return pct(Decimal(numerator) * Decimal(100) / Decimal(denominator))


def expected_prorated_tax_cents(annual_tax_cents: int, remaining_days: int) -> int:
    return cents(
        Decimal(annual_tax_cents) * Decimal(remaining_days) / Decimal(C.FISCAL_YEAR_DAYS)
    )


def expected_daily_proration_refund_cents(
    posted_tax_cents: int, effective_date: str, fiscal_year_end_month_day: str
) -> int:
    days = remaining_fiscal_days(effective_date, fiscal_year_end_month_day)
    return cents(Decimal(posted_tax_cents) * Decimal(days) / Decimal(C.FISCAL_YEAR_DAYS))


def expected_whole_quarter_refund_cents(posted_tax_cents: int, effective_date: str) -> int:
    quarters = remaining_quarters(effective_date)
    return cents(
        Decimal(posted_tax_cents) * Decimal(quarters) / Decimal(C.QUARTERS_PER_YEAR)
    )


def expected_msd_assessment_cents(committed_cost_cents: int, msd_cost_recovery_pct) -> int:
    return cents(Decimal(committed_cost_cents) * Decimal(str(msd_cost_recovery_pct)))


def expected_outside_city_monthly_cents(monthly_base_cents: int, surcharge_pct) -> int:
    return cents(
        Decimal(monthly_base_cents) * (Decimal(1) + Decimal(str(surcharge_pct)))
    )


def ordered_service_types(service_types: Iterable[str]) -> List[str]:
    """The distinct set ordered by the fixed sequence POLICE, FIRE, WATER,
    SEWER regardless of creation order."""
    present = set(service_types)
    return [s for s in C.SERVICE_TYPE_ORDER if s in present]


# ==========================================================================
# Shape assertions
# ==========================================================================
def assert_identity_fields(entity: Dict[str, Any]) -> None:
    """Every resource carries a server-minted UUID `id` and an ISO 8601
    `created_at`."""
    assert is_valid_uuid(entity.get("id")), f"expected a UUID id, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(
        entity.get("created_at")
    ), f"expected an ISO 8601 created_at, got {entity.get('created_at')!r}"


def assert_revision_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Resources other than NoticePublication also carry `updated_at` and an
    integer `version` starting at 1."""
    assert_identity_fields(entity)
    assert is_iso8601_timestamp(
        entity.get("updated_at")
    ), f"expected an ISO 8601 updated_at, got {entity.get('updated_at')!r}"
    assert isinstance(entity.get("version"), int), "expected an integer version"
    assert entity["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_notice_shape(notice: Dict[str, Any]) -> None:
    """A published notice carries only `id` and `created_at`: no `updated_at`
    and no `version`."""
    assert_identity_fields(notice)
    assert "updated_at" not in notice, "a notice publication has no updated_at field"
    assert "version" not in notice, "a notice publication has no version field"


def assert_echoes(entity: Dict[str, Any], payload: Dict[str, Any]) -> None:
    """Every field supplied on creation is echoed back unchanged."""
    for key, value in payload.items():
        assert key in entity, f"response is missing the submitted field {key!r}"
        assert entity[key] == value, (
            f"{key}: submitted {value!r} but stored {entity[key]!r}"
        )


def assert_numeric_equals(actual, expected, field: str = "value", places: int = 2) -> None:
    assert approx_equal(actual, expected, places), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_id_set(records: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """The collection contains exactly the expected ids, order-insensitively."""
    actual = {r["id"] for r in records}
    expected = set(expected_ids)
    assert actual == expected, f"expected ids {sorted(expected)}, got {sorted(actual)}"


def assert_id_order(records: Iterable[Dict[str, Any]], expected_ids: List[str]) -> None:
    """The collection contains exactly the expected ids in exactly that
    order."""
    actual = [r["id"] for r in records]
    assert actual == list(expected_ids), f"expected order {expected_ids}, got {actual}"
