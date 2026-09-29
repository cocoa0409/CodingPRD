"""Per-entity shape assertions and domain invariant checkers."""

import re
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    CATEGORY_WEIGHT,
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    SERVICE_TYPES,
    SEVERITY_WEIGHT,
    TIER_WAIVER_RATE,
)
from .types import (
    ADDRESS_POINT_STATUSES,
    ADDRESS_SOURCES,
    AGENCY_STATUSES,
    AGENCY_TYPES,
    BOUNDARY_STATUSES,
    CASE_STATUSES,
    CASE_SUBJECT_TYPES,
    CELL_ASSIGNMENT_STATUSES,
    CONFIDENCE_BASES,
    DEFECT_CATEGORIES,
    DEFECT_SEVERITIES,
    FULFILLMENT_STATUSES,
    JURISDICTION_TYPES,
    PACKAGE_CHANNELS,
    PACKAGE_RECORD_TYPES,
    PACKAGE_STATUSES,
    PARITIES,
    PIN_STATES,
    PROPOSAL_PROJECTED_STATUSES,
    PROPOSAL_SIDES,
    QC_DEFECT_STATUSES,
    QC_REPORT_STATUSES,
    QC_SCOPES,
    QUALITY_TIERS,
    REVIEW_STATUSES,
    ROAD_STATUSES,
    SIDES,
    UTILITY_STATUSES,
)

# Every datetime crossing the API boundary carries exactly three fractional
# digits and a trailing Z.
EXACT_MILLIS_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Primitive assertions
# ---------------------------------------------------------------------------
def assert_exact_millisecond_timestamp(value: Any, field: str = "timestamp") -> None:
    """Assert an ISO 8601 UTC stamp in the shape YYYY-MM-DDTHH:MM:SS.mmmZ."""
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert EXACT_MILLIS_ISO.match(value), (
        f"{field} must carry exactly three fractional digits and a trailing Z, "
        f"got {value!r}"
    )


def assert_two_decimal_number(value: Any, field: str = "score") -> None:
    """Assert a JSON number carried to at most two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, not {type(value)}: {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )


def assert_score_equals(value: Any, expected: float, field: str = "score") -> None:
    assert_two_decimal_number(value, field)
    assert abs(float(value) - expected) < 1e-9, (
        f"{field} expected {expected:.2f}, got {value!r}"
    )


def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None):
    """id / created_at / updated_at / version, carried by every entity but
    DiscrepancyProposal."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID, got {record['id']!r}"
    assert_exact_millisecond_timestamp(record["created_at"], "created_at")
    assert_exact_millisecond_timestamp(record["updated_at"], "updated_at")
    assert isinstance(record["version"], int) and not isinstance(
        record["version"], bool
    ), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"version expected {expected_version}, got {record['version']}"
        )


def assert_log_row_fields(record: Dict[str, Any]) -> None:
    """A DiscrepancyProposal carries only id and created_at."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID, got {record['id']!r}"
    assert_exact_millisecond_timestamp(record["created_at"], "created_at")
    assert "updated_at" not in record, "DiscrepancyProposal has no updated_at"
    assert "version" not in record, "DiscrepancyProposal has no version"


def assert_enum(value: Any, allowed: Sequence[str], field: str) -> None:
    assert value in allowed, f"{field} must be one of {list(allowed)}, got {value!r}"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_jurisdiction(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["jurisdiction_type"], JURISDICTION_TYPES, "jurisdiction_type")
    for counter in (
        "cell_count",
        "covered_cell_count",
        "gap_pair_count",
        "forward_gap_pair_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must not be negative"
    assert data["postal_city"] == data["postal_city"].upper(), (
        "postal_city is stored uppercased"
    )
    _assert_expected(data, expected)


def assert_agency(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["agency_type"], AGENCY_TYPES, "agency_type")
    assert_enum(data["status"], AGENCY_STATUSES, "status")
    assert is_valid_uuid(data["jurisdiction_id"])
    _assert_expected(data, expected)


def assert_coverage_cell(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0
    _assert_expected(data, expected)


def assert_road_centerline(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["status"], ROAD_STATUSES, "status")
    assert_enum(data["parity_left"], PARITIES, "parity_left")
    assert_enum(data["parity_right"], PARITIES, "parity_right")
    assert data["parity_left"] != data["parity_right"], (
        "the two sides' parities must differ from each other"
    )
    assert isinstance(data["qc_dirty"], bool)
    assert isinstance(data["open_discrepancy_case_count"], int)
    assert data["assignable_slot_count_left"] >= 0
    assert data["assignable_slot_count_right"] >= 0
    _assert_expected(data, expected)


def assert_address_point(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["status"], ADDRESS_POINT_STATUSES, "status")
    assert_enum(data["source"], ADDRESS_SOURCES, "source")
    assert_enum(data["side"], SIDES, "side")
    assert_enum(data["confidence_basis"], CONFIDENCE_BASES, "confidence_basis")
    assert_two_decimal_number(data["confidence_score"], "confidence_score")
    assert CONFIDENCE_MIN <= data["confidence_score"] <= CONFIDENCE_MAX
    if data.get("certified_confidence_score") is not None:
        assert_two_decimal_number(
            data["certified_confidence_score"], "certified_confidence_score"
        )
        assert (
            CONFIDENCE_MIN <= data["certified_confidence_score"] <= CONFIDENCE_MAX
        )
    assert data["postal_city"] == data["postal_city"].upper()
    _assert_expected(data, expected)


def assert_assignment_request(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["review_status"], REVIEW_STATUSES, "review_status")
    assert_enum(data["utility_status"], UTILITY_STATUSES, "utility_status")
    assert_enum(data["fulfillment_status"], FULFILLMENT_STATUSES, "fulfillment_status")
    assert isinstance(data["minted_point_count"], int)
    _assert_expected(data, expected)


def assert_boundary(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["status"], BOUNDARY_STATUSES, "status")
    assert_enum(data["service_type"], SERVICE_TYPES, "service_type")
    assert_exact_millisecond_timestamp(data["effective_start"], "effective_start")
    if data.get("effective_end") is not None:
        assert_exact_millisecond_timestamp(data["effective_end"], "effective_end")
    assert isinstance(data["assigned_cell_count"], int)
    _assert_expected(data, expected)


def assert_cell_assignment(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["status"], CELL_ASSIGNMENT_STATUSES, "status")
    assert_enum(data["service_type"], SERVICE_TYPES, "service_type")
    assert_exact_millisecond_timestamp(data["effective_start"], "effective_start")
    if data.get("effective_end") is not None:
        assert_exact_millisecond_timestamp(data["effective_end"], "effective_end")
    _assert_expected(data, expected)


def assert_qc_report(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["scope"], QC_SCOPES, "scope")
    assert_enum(data["status"], QC_REPORT_STATUSES, "status")
    assert_enum(data["quality_tier"], QUALITY_TIERS, "quality_tier")
    for score in (
        "quality_score",
        "advisory_quality_score",
        "provisioning_eligibility_score",
    ):
        assert_two_decimal_number(data[score], score)
    assert isinstance(data["is_provisioning_eligible"], bool)
    _assert_expected(data, expected)


def assert_qc_defect(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["severity"], DEFECT_SEVERITIES, "severity")
    assert_enum(data["defect_category"], DEFECT_CATEGORIES, "defect_category")
    assert_enum(data["status"], QC_DEFECT_STATUSES, "status")
    _assert_expected(data, expected)


def assert_package(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["channel"], PACKAGE_CHANNELS, "channel")
    assert_enum(data["status"], PACKAGE_STATUSES, "status")
    assert isinstance(data["drift_detected"], bool)
    assert data["fresh_pin_count"] + data["stale_pin_count"] == data[
        "pinned_record_count"
    ], "fresh_pin_count plus stale_pin_count must equal pinned_record_count"
    assert data["drift_detected"] == (data["stale_pin_count"] > 0), (
        "drift_detected is true exactly when stale_pin_count is greater than zero"
    )
    _assert_expected(data, expected)


def assert_package_record(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["record_type"], PACKAGE_RECORD_TYPES, "record_type")
    assert_enum(data["pin_state"], PIN_STATES, "pin_state")
    assert isinstance(data["pinned_version"], int)
    if data["pin_state"] == "FRESH":
        assert data.get("staled_at") is None, "a FRESH pin has a null staled_at"
    _assert_expected(data, expected)


def assert_discrepancy_case(data: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data)
    assert_enum(data["subject_type"], CASE_SUBJECT_TYPES, "subject_type")
    assert_enum(data["status"], CASE_STATUSES, "status")
    assert isinstance(data["round_count"], int)
    _assert_expected(data, expected)


def assert_discrepancy_proposal(data: Dict[str, Any], **expected: Any) -> None:
    assert_log_row_fields(data)
    assert_enum(data["proposed_by_side"], PROPOSAL_SIDES, "proposed_by_side")
    assert_enum(data["status"], PROPOSAL_PROJECTED_STATUSES, "status")
    assert isinstance(data["round_number"], int)
    _assert_expected(data, expected)


def _assert_expected(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    for field, value in expected.items():
        assert field in data, f"response is missing {field}"
        if isinstance(value, float):
            assert abs(float(data[field]) - value) < 1e-9, (
                f"{field} expected {value}, got {data[field]!r}"
            )
        else:
            assert data[field] == value, (
                f"{field} expected {value!r}, got {data[field]!r}"
            )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_service_type_order(values: Sequence[str], field: str = "array") -> None:
    """Every service-type array is the sequence LAW, FIRE, EMS filtered in order."""
    assert list(values) == [s for s in SERVICE_TYPES if s in values], (
        f"{field} must be emitted in the fixed order LAW, FIRE, EMS, got {list(values)}"
    )


def assert_coverage_status_shape(data: Dict[str, Any]) -> None:
    for field in (
        "covered_service_types",
        "gap_service_types",
        "proposed_conflict_service_types",
        "forward_gap_service_types",
    ):
        assert isinstance(data[field], list), f"{field} must be an array"
        assert_service_type_order(data[field], field)
    assert_exact_millisecond_timestamp(data["evaluated_at"], "evaluated_at")
    assert isinstance(data["responding_assignment_count"], int)


def assert_coverage_pair_conservation(
    coverage_status: Dict[str, Any], total_service_types: int = 3
) -> None:
    """For every cell, covered service types plus gap service types is three."""
    covered = len(coverage_status["covered_service_types"])
    gap = len(coverage_status["gap_service_types"])
    assert covered + gap == total_service_types, (
        f"covered ({covered}) plus gap ({gap}) must be {total_service_types}"
    )


def expected_slot_capacity(low: int, high: int) -> int:
    """Capacity for one side: ((high - low) // 2) + 1."""
    return ((high - low) // 2) + 1


def assert_slot_counters(
    road: Dict[str, Any], expected_left: int, expected_right: int
) -> None:
    assert road["assignable_slot_count_left"] == expected_left, (
        f"assignable_slot_count_left expected {expected_left}, "
        f"got {road['assignable_slot_count_left']}"
    )
    assert road["assignable_slot_count_right"] == expected_right, (
        f"assignable_slot_count_right expected {expected_right}, "
        f"got {road['assignable_slot_count_right']}"
    )


def round_half_up(value: float, digits: int = 2) -> float:
    """Round half up, the rounding mode every score in this system uses."""
    from decimal import Decimal, ROUND_HALF_UP

    quant = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(value)).quantize(quant, rounding=ROUND_HALF_UP))


def expected_quality_score(
    deductions_by_category: Dict[str, float],
) -> float:
    """Per-category round, then sum, then round again."""
    total = 0.0
    for category, weight in CATEGORY_WEIGHT.items():
        deduction = deductions_by_category.get(category, 0.0)
        category_score = max(0.0, 100.0 - deduction)
        total += round_half_up(category_score * weight, 2)
    return round_half_up(total, 2)


def expected_deduction(severity_counts: Dict[str, int]) -> float:
    return sum(
        SEVERITY_WEIGHT[severity] * count for severity, count in severity_counts.items()
    )


def expected_eligibility_score(
    quality_score: float, quality_tier: str, waived_blocking_count: int
) -> float:
    """Base minus waived_blocking_count times the tier rate, floored at zero."""
    penalty = waived_blocking_count * TIER_WAIVER_RATE[quality_tier]
    return round_half_up(max(0.0, quality_score - penalty), 2)


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"collections are always sorted by created_at ascending, got {stamps}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, returned: int
) -> None:
    assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] == (offset + returned < total_count), (
        "has_more is true when offset plus the rows returned is less than total_count"
    )
