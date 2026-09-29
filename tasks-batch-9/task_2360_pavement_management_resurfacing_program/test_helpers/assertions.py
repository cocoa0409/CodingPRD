"""Domain assertions for the Pavement Management & Resurfacing Program API.

These wrap the repetitive checks the PRD's precision, banding, parallel-state and
conserved-quantity rules demand, so individual tests read as statements about
pavement rather than as dictionary plumbing.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BAND_FAILED,
    BAND_FAIR,
    BAND_GOOD,
    BAND_POOR,
    BAND_FAIR_FLOOR,
    BAND_GOOD_FLOOR,
    BAND_POOR_FLOOR,
)


# ----------------------------------------------------------------------
# Identity and audit
# ----------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a UUID id, ISO-8601 stamps and an integer version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be ISO 8601, got {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be ISO 8601, got {row.get('updated_at')!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version']} + {by}, got {after['version']}"
    )


def assert_three_fraction_digits(value: str) -> None:
    """Timestamps render as ISO 8601 UTC instants with three fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value!r}"
    assert "." in value, f"timestamp {value!r} carries no fractional digits"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp {value!r} must carry exactly three fractional digits"
    )


# ----------------------------------------------------------------------
# Precision
# ----------------------------------------------------------------------
def assert_decimals(value: float, places: int, label: str = "value") -> None:
    assert value is not None, f"{label} must not be null"
    quantized = round(float(value), places)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{label} {value} carries more than {places} decimal places"
    )


def assert_area(value: float, expected: float) -> None:
    """Pavement areas carry two decimal places."""
    assert_decimals(value, 2, "area")
    assert value == expected, f"expected area {expected}, got {value}"


def assert_index(value: float, expected: float) -> None:
    """Condition indices carry one decimal place."""
    assert_decimals(value, 1, "condition index")
    assert value == expected, f"expected condition index {expected}, got {value}"


def assert_money(value: Any, expected: int, label: str = "amount") -> None:
    """Money is held in integer cents throughout, with no fractional cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be integer cents, got {value!r}"
    )
    assert value == expected, f"expected {label} {expected} cents, got {value} cents"


def assert_four_decimals(value: float, expected: float, label: str = "ratio") -> None:
    assert_decimals(value, 4, label)
    assert value == expected, f"expected {label} {expected}, got {value}"


# ----------------------------------------------------------------------
# Condition banding
# ----------------------------------------------------------------------
def expected_band(index: float) -> str:
    if index >= BAND_GOOD_FLOOR:
        return BAND_GOOD
    if index >= BAND_FAIR_FLOOR:
        return BAND_FAIR
    if index >= BAND_POOR_FLOOR:
        return BAND_POOR
    return BAND_FAILED


def assert_segment_condition(
    segment: Dict[str, Any], index: float, source: str, band: Optional[str] = None
) -> None:
    assert_index(segment["condition_index"], index)
    assert segment["condition_index_source"] == source, (
        f"expected condition_index_source {source}, got {segment['condition_index_source']}"
    )
    expected = band or expected_band(index)
    assert segment["condition_band"] == expected, (
        f"expected condition_band {expected}, got {segment['condition_band']}"
    )


# ----------------------------------------------------------------------
# Parallel state dimensions
# ----------------------------------------------------------------------
def assert_project_states(project: Dict[str, Any], delivery: str, quality: str) -> None:
    assert project["delivery_status"] == delivery, (
        f"expected delivery_status {delivery}, got {project['delivery_status']}"
    )
    assert project["quality_status"] == quality, (
        f"expected quality_status {quality}, got {project['quality_status']}"
    )


def assert_line_states(line: Dict[str, Any], work: str, notice: str) -> None:
    assert line["work_state"] == work, (
        f"expected work_state {work}, got {line['work_state']}"
    )
    assert line["notice_state"] == notice, (
        f"expected notice_state {notice}, got {line['notice_state']}"
    )


# ----------------------------------------------------------------------
# Aggregates and conserved quantities
# ----------------------------------------------------------------------
def assert_project_estimate(
    project: Dict[str, Any],
    base: int,
    contingency: int,
    utility_share: int,
    total: int,
) -> None:
    assert_money(project["bundle_base_cents"], base, "bundle_base_cents")
    assert_money(project["contingency_cents"], contingency, "contingency_cents")
    assert_money(project["utility_share_cents"], utility_share, "utility_share_cents")
    assert_money(project["project_total_estimate_cents"], total, "project_total_estimate_cents")
    assert base + contingency + utility_share == total, (
        "project_total_estimate_cents must equal base plus contingency plus utility share"
    )


def assert_project_scope(project: Dict[str, Any], segment_count: int, area: float) -> None:
    assert project["segment_count"] == segment_count, (
        f"expected segment_count {segment_count}, got {project['segment_count']}"
    )
    assert_area(project["planned_area_sy"], area)


def assert_scenario_funding(
    scenario: Dict[str, Any], funding: int, committed: int, uncommitted: int
) -> None:
    assert_money(scenario["funding_cents"], funding, "funding_cents")
    assert_money(scenario["committed_cents"], committed, "committed_cents")
    assert_money(scenario["uncommitted_cents"], uncommitted, "uncommitted_cents")
    assert committed + uncommitted == funding, (
        "the funding total must equal committed plus uncommitted, exactly"
    )


def assert_scenario_totals(
    scenario: Dict[str, Any], allocation_count: int, funded: int, backlog: int
) -> None:
    assert scenario["allocation_count"] == allocation_count, (
        f"expected allocation_count {allocation_count}, got {scenario['allocation_count']}"
    )
    assert_money(scenario["funded_cost_cents"], funded, "funded_cost_cents")
    assert_money(scenario["backlog_cents"], backlog, "backlog_cents")


# ----------------------------------------------------------------------
# Quality acceptance
# ----------------------------------------------------------------------
def assert_pay_factor(test: Dict[str, Any], pay_factor: float, outcome: str) -> None:
    assert_four_decimals(test["computed_pay_factor"], pay_factor, "computed_pay_factor")
    assert test["computed_outcome"] == outcome, (
        f"expected computed_outcome {outcome}, got {test['computed_outcome']}"
    )


def assert_contractor_standing(
    contractor: Dict[str, Any], standing: str, interim: Optional[float]
) -> None:
    assert contractor["standing"] == standing, (
        f"expected standing {standing}, got {contractor['standing']}"
    )
    if interim is None:
        assert contractor["interim_performance_score"] is None
    else:
        assert_decimals(contractor["interim_performance_score"], 1, "interim_performance_score")
        assert contractor["interim_performance_score"] == interim, (
            f"expected interim_performance_score {interim}, "
            f"got {contractor['interim_performance_score']}"
        )


# ----------------------------------------------------------------------
# Listing helpers
# ----------------------------------------------------------------------
def assert_ordered_ascending(rows: Sequence[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not ordered by {field} ascending: {values}"


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by(rows: Sequence[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    for row in rows:
        if row.get(field) == value:
            return row
    raise AssertionError(f"no row with {field} == {value!r} among {len(rows)} rows")


def assert_envelope_is_array(body: Dict[str, Any]) -> None:
    assert body["response_type"] == "array", (
        f"expected response_type 'array', got {body['response_type']!r}"
    )


def assert_request_id_prefixed(meta: Dict[str, Any]) -> None:
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
