"""
Domain assertions and small arithmetic helpers.

The ``assert_<entity>`` helpers check the four system-managed properties of PRD
2.4 and then any expected field values passed by keyword, so a test reads as a
list of the facts it is pinning rather than a wall of dictionary lookups.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import StockFinding


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------


def round_half_up(value: float, decimals: int = 0) -> float:
    """
    Round half up, the rounding mode this API uses everywhere.

    ``decimals=0`` returns a whole-cent float (compare against an int with ``==``),
    ``decimals=1`` the one-decimal form used by ``stock_compliance_pct`` and
    ``risk_score``.
    """
    quantum = Decimal(1).scaleb(-decimals)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(result)


def round_half_up_cents(value: float) -> int:
    """Round half up to a whole cent and return it as an integer."""
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# Envelope and common-field helpers
# ---------------------------------------------------------------------------


def assert_field_values(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert each expected field is present on the entity with the given value."""
    for field, value in expected.items():
        assert field in entity, f"expected field {field!r} to be present, got {entity}"
        assert entity[field] == value, (
            f"expected {field!r} to be {value!r}, got {entity[field]!r}"
        )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a UUID id, two timestamps, and an integer version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 timestamp: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO 8601 timestamp: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), (
        f"version is not an integer: {entity['version']!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_iso_millis(value: str) -> None:
    """Instants are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert "." in value and value.endswith("Z"), (
        f"expected three fractional digits and a Z suffix: {value!r}"
    )
    assert len(value.split(".")[1]) == 4, (
        f"expected exactly three fractional digits: {value!r}"
    )


def assert_no_data_payload(response) -> None:
    """
    An error envelope carries only ``error_id`` and ``message`` under ``data``.

    Used where a test needs to show that a failed read returned no resource.
    """
    body = response.json()
    assert body.get("response_type") == "error", f"expected an error envelope: {body}"
    assert set(body["data"].keys()) <= {"error_id", "message"}, (
        f"error data carried more than error_id and message: {body['data']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_peer_group(peer_group: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(peer_group)
    assert_field_values(peer_group, **expected)


def assert_food_category(category: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(category)
    assert_field_values(category, **expected)


def assert_authorized_food_item(item: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(item)
    assert_field_values(item, **expected)


def assert_vendor(vendor: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(vendor)
    assert_field_values(vendor, **expected)


def assert_price_cycle(cycle: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(cycle)
    assert_field_values(cycle, **expected)


def assert_price_submission(submission: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(submission)
    assert_field_values(submission, **expected)


def assert_price_ceiling(ceiling: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(ceiling)
    assert_field_values(ceiling, **expected)


def assert_monitoring_visit(visit: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(visit)
    assert_field_values(visit, **expected)


def assert_redemption_claim(claim: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(claim)
    assert_field_values(claim, **expected)


def assert_claim_line(line: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(line)
    assert_field_values(line, **expected)


def assert_reimbursement_adjustment(
    adjustment: Dict[str, Any], **expected: Any
) -> None:
    assert_common_fields(adjustment)
    assert_field_values(adjustment, **expected)


def assert_sanction_case(case: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(case)
    assert_field_values(case, **expected)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def find_stock_finding(
    visit: Dict[str, Any], food_category_id: str
) -> StockFinding:
    """Return the visit's stock finding for one category, failing if absent."""
    findings = visit.get("stock_findings") or []
    for finding in findings:
        if finding.get("food_category_id") == food_category_id:
            return finding
    raise AssertionError(
        f"no stock finding for category {food_category_id!r} in {findings}"
    )


def assert_stock_finding(
    visit: Dict[str, Any],
    food_category_id: str,
    required_units: Optional[int] = None,
    verdict: Optional[str] = None,
    observed_units: Optional[int] = None,
    observed_variety_count: Optional[int] = None,
) -> StockFinding:
    """Assert the requirement, verdict and observation stamped for one category."""
    finding = find_stock_finding(visit, food_category_id)
    if required_units is not None:
        assert finding.get("required_units") == required_units, (
            f"expected required_units {required_units}, got {finding}"
        )
    if verdict is not None:
        assert finding.get("verdict") == verdict, (
            f"expected verdict {verdict!r}, got {finding}"
        )
    if observed_units is not None:
        assert finding.get("observed_units") == observed_units, (
            f"expected observed_units {observed_units}, got {finding}"
        )
    if observed_variety_count is not None:
        assert finding.get("observed_variety_count") == observed_variety_count, (
            f"expected observed_variety_count {observed_variety_count}, got {finding}"
        )
    return finding


def assert_line_recoupments(
    adjustment: Dict[str, Any], expected: List[Dict[str, Any]]
) -> None:
    """
    Assert the per-line proration, in order.

    ``expected`` is a list of dicts holding the ``allowed_cents`` and
    ``recoupment_cents`` expected for each participating line, in ascending
    ``line_number`` order, which is the order the PRD pins the entries in.
    """
    entries = adjustment.get("line_recoupments")
    assert isinstance(entries, list), (
        f"line_recoupments is not a list: {adjustment.get('line_recoupments')!r}"
    )
    assert len(entries) == len(expected), (
        f"expected {len(expected)} line_recoupments entries, got {entries}"
    )
    for index, (entry, want) in enumerate(zip(entries, expected)):
        for field, value in want.items():
            assert entry.get(field) == value, (
                f"line_recoupments[{index}].{field}: expected {value!r}, got {entry!r}"
            )


def assert_proration_sums_per_line(adjustment: Dict[str, Any]) -> None:
    """
    The adjustment total is the sum of the individually rounded per-line shares.

    This is the "per line first, then sum" rule: the residual against rounding the
    claim total once is deliberately not redistributed.
    """
    entries = adjustment.get("line_recoupments") or []
    per_line_sum = sum(entry["recoupment_cents"] for entry in entries)
    assert adjustment["recoupment_cents"] == per_line_sum, (
        f"recoupment_cents {adjustment['recoupment_cents']} is not the sum of the "
        f"per-line shares {per_line_sum}"
    )


def assert_claim_net_payable(claim: Dict[str, Any], applied_recoupment_cents: int) -> None:
    """``net_payable_cents`` is the adjudicated total less the applied recoupments."""
    expected = claim["adjudicated_total_cents"] - applied_recoupment_cents
    assert claim["net_payable_cents"] == expected, (
        f"expected net_payable_cents {expected} "
        f"(adjudicated_total_cents {claim['adjudicated_total_cents']} less "
        f"{applied_recoupment_cents}), got {claim['net_payable_cents']}"
    )


def assert_claim_line_counts(claim: Dict[str, Any], lines: List[Dict[str, Any]]) -> None:
    """The three line counters tally the edit results over every line."""
    accepted = sum(1 for line in lines if line["edit_result"] == "ACCEPTED")
    reduced = sum(1 for line in lines if line["edit_result"] == "ACCEPTED_REDUCED")
    rejected = sum(1 for line in lines if line["edit_result"] == "REJECTED")
    assert claim["accepted_line_count"] == accepted, (
        f"expected accepted_line_count {accepted}, got {claim['accepted_line_count']}"
    )
    assert claim["reduced_line_count"] == reduced, (
        f"expected reduced_line_count {reduced}, got {claim['reduced_line_count']}"
    )
    assert claim["rejected_line_count"] == rejected, (
        f"expected rejected_line_count {rejected}, got {claim['rejected_line_count']}"
    )


def assert_adjudicated_total_is_sum_of_allowed(
    claim: Dict[str, Any], lines: List[Dict[str, Any]]
) -> None:
    """``adjudicated_total_cents`` is the sum of ``allowed_cents`` over all lines."""
    total = sum(line["allowed_cents"] for line in lines)
    assert claim["adjudicated_total_cents"] == total, (
        f"expected adjudicated_total_cents {total}, "
        f"got {claim['adjudicated_total_cents']}"
    )


def assert_risk_score_components(
    profile: Dict[str, Any],
    edit_rejection_rate_pct: float,
    price_excess_pct: float,
    failed_visit_pct: float,
    sanction_points: int,
    expected_score: float,
    expected_tier: str,
) -> None:
    """Assert the three component percentages and the weighted score they yield."""
    assert_field_values(
        profile,
        edit_rejection_rate_pct=edit_rejection_rate_pct,
        price_excess_pct=price_excess_pct,
        failed_visit_pct=failed_visit_pct,
        sanction_points=sanction_points,
        risk_score=expected_score,
        risk_tier=expected_tier,
    )


def assert_ceiling_derivation(
    ceiling: Dict[str, Any],
    basis: str,
    peer_submission_count: int,
    contributing_submission_count: int,
    base_cents: float,
    cap_cents: float,
    cap_binding: bool,
    mar_cents: int,
) -> None:
    """
    Assert one maximum allowable reimbursement row against the pinned derivation.

    ``base_cents`` and ``cap_cents`` remain unrounded decimals on the row, and the
    single rounding half up produces ``mar_cents``.
    """
    assert ceiling["basis"] == basis, (
        f"expected basis {basis!r}, got {ceiling['basis']!r}"
    )
    assert ceiling["peer_submission_count"] == peer_submission_count, (
        f"expected peer_submission_count {peer_submission_count}, got {ceiling}"
    )
    assert ceiling["contributing_submission_count"] == contributing_submission_count, (
        f"expected contributing_submission_count {contributing_submission_count}, "
        f"got {ceiling}"
    )
    assert float(ceiling["base_cents"]) == float(base_cents), (
        f"expected base_cents {base_cents}, got {ceiling['base_cents']}"
    )
    assert float(ceiling["cap_cents"]) == float(cap_cents), (
        f"expected cap_cents {cap_cents}, got {ceiling['cap_cents']}"
    )
    assert ceiling["cap_binding"] is cap_binding, (
        f"expected cap_binding {cap_binding}, got {ceiling['cap_binding']!r}"
    )
    assert ceiling["mar_cents"] == mar_cents, (
        f"expected mar_cents {mar_cents}, got {ceiling['mar_cents']}"
    )


def assert_sanction_schedule(
    case: Dict[str, Any],
    base_tier: int,
    case_points: int,
    cumulative_points_at_open: int,
    effective_tier: int,
    disqualification_months: int,
    cmp_permitted: bool,
    cmp_amount_cents: int,
) -> None:
    """Assert every figure the one-pass sanction schedule fixes at open time."""
    assert_field_values(
        case,
        base_tier=base_tier,
        case_points=case_points,
        cumulative_points_at_open=cumulative_points_at_open,
        effective_tier=effective_tier,
        disqualification_months=disqualification_months,
        cmp_permitted=cmp_permitted,
        cmp_amount_cents=cmp_amount_cents,
    )
