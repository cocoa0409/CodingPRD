"""Domain assertions for the HOA Declarant Turnover API.

These wrap the framework's structural helpers with the PRD's own vocabulary so
a failing test names the rule it broke.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ADEQUACY_UNDETERMINED,
    CANCELLATION_WINDOW_DAYS,
    MONTHS_PER_YEAR,
)

# ─── Common fields (§2.4) ─────────────────────────────


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource.get("id", "")), (
        f"id must be a server-minted UUID with no type prefix, got {resource.get('id')!r}"
    )
    assert_timestamp_format(resource["created_at"])
    assert "updated_at" in resource, "No resource in this system omits updated_at"
    assert_timestamp_format(resource["updated_at"])
    assert "version" in resource, "No resource in this system omits version"
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"Expected version {expected_version}, got {resource['version']}"
        )


def assert_created_fresh(resource: Dict[str, Any]) -> None:
    """A freshly created resource starts at version 1."""
    assert_common_fields(resource, expected_version=1)


# ─── Money and percentages (§2.6) ─────────────────────


def assert_cents_integer(value: Any, field_name: str = "amount_cents") -> None:
    """A field name ending in _cents never carries a fractional part."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


def assert_all_cents_integers(resource: Dict[str, Any]) -> None:
    for key, value in resource.items():
        if key.endswith("_cents") and value is not None:
            assert_cents_integer(value, key)


def assert_pct(actual: Any, expected: float, field_name: str = "percentage") -> None:
    """Percentages are carried to exactly two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{field_name}: expected {expected}, got {actual}"
    )


def assert_two_decimal_places(value: Any, field_name: str = "percentage") -> None:
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field_name} must carry at most two decimal places, got {value!r}"
    )


# ─── Envelope (§2.2) ──────────────────────────────────


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp with three "
        f"fractional digits, got {meta['api_request_timestamp']!r}"
    )


def assert_error_envelope_shape(body: Dict[str, Any]) -> None:
    """§2.2: error meta contains only api_request_id and api_request_timestamp."""
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "The meta object for error responses contains only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"Error data must carry exactly error_id and message, got {sorted(body['data'].keys())}"
    )


# ─── Pagination (§2.3) ────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: int,
    expected_limit: int,
    expected_offset: int,
    expected_has_more: bool,
) -> None:
    assert meta["total_count"] == expected_total, (
        f"total_count is the size of the filtered set before the window is "
        f"applied: expected {expected_total}, got {meta['total_count']}"
    )
    assert meta["limit"] == expected_limit
    assert meta["offset"] == expected_offset
    assert meta["has_more"] is expected_has_more


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at ascending order: {stamps}"


# ─── Turnover posture (§2.8) ──────────────────────────


def assert_posture(case: Dict[str, Any], expected: str) -> None:
    assert case["turnover_posture"] == expected, (
        f"Expected turnover_posture {expected}, got {case['turnover_posture']} "
        f"(governance {case.get('governance_status')}, financial {case.get('financial_status')})"
    )


def assert_dimensions(
    case: Dict[str, Any], governance: str, financial: str, posture: Optional[str] = None
) -> None:
    assert case["governance_status"] == governance, (
        f"Expected governance_status {governance}, got {case['governance_status']}"
    )
    assert case["financial_status"] == financial, (
        f"Expected financial_status {financial}, got {case['financial_status']}"
    )
    if posture is not None:
        assert_posture(case, posture)


# ─── Seat ledger (§3.4) ───────────────────────────────


def assert_seat_ledger(
    case: Dict[str, Any],
    declarant_appointed: int,
    owner_elected: int,
    vacant: int,
    total_seats: Optional[int] = None,
) -> None:
    """total_seats always equals the number of SEATED directors plus vacant_seats."""
    assert case["declarant_appointed_seats"] == declarant_appointed, (
        f"Expected declarant_appointed_seats {declarant_appointed}, "
        f"got {case['declarant_appointed_seats']}"
    )
    assert case["owner_elected_seats"] == owner_elected, (
        f"Expected owner_elected_seats {owner_elected}, got {case['owner_elected_seats']}"
    )
    assert case["vacant_seats"] == vacant, (
        f"Expected vacant_seats {vacant}, got {case['vacant_seats']}"
    )
    if total_seats is not None:
        assert case["total_seats"] == total_seats
    assert (
        case["total_seats"]
        == case["declarant_appointed_seats"] + case["owner_elected_seats"] + case["vacant_seats"]
    ), (
        "Seat ledger does not balance: total_seats must equal the number of "
        f"SEATED directors plus vacant_seats, got {case}"
    )


# ─── Claim pool invariant (§3.8) ──────────────────────


def assert_claim_pool_conserved(association: Dict[str, Any]) -> None:
    """reserve_claim_committed_cents plus reserve_claim_available_cents equals the pool."""
    committed = association["reserve_claim_committed_cents"]
    available = association["reserve_claim_available_cents"]
    pool = association["reserve_claim_pool_cents"]
    assert committed + available == pool, (
        f"Claim pool not conserved: committed {committed} + available {available} "
        f"!= pool {pool}"
    )


def assert_claim_reserve_breakdown(
    claim: Dict[str, Any], subtotal: int, fee: int, reserved: int
) -> None:
    assert claim["reserve_subtotal_cents"] == subtotal, (
        f"Expected reserve_subtotal_cents {subtotal}, got {claim['reserve_subtotal_cents']}"
    )
    assert claim["litigation_admin_fee_cents"] == fee, (
        f"Expected litigation_admin_fee_cents {fee}, got {claim['litigation_admin_fee_cents']}"
    )
    assert claim["reserved_amount_cents"] == reserved, (
        f"Expected reserved_amount_cents {reserved}, got {claim['reserved_amount_cents']}"
    )
    assert subtotal + fee == reserved, (
        "reserved_amount_cents is the subtotal plus the fee"
    )


# ─── Reserve study verdicts (§3.7) ────────────────────


def assert_study_evaluation(
    study: Dict[str, Any],
    evaluated_method: Optional[str],
    verdict: str,
    recommendation: int,
    component_count: Optional[int] = None,
    fully_funded_balance: Optional[int] = None,
    percent_funded: Optional[float] = None,
    min_projected_balance: Optional[int] = None,
) -> None:
    assert study["evaluated_method"] == evaluated_method, (
        f"Expected evaluated_method {evaluated_method}, got {study['evaluated_method']}"
    )
    assert study["adequacy_verdict"] == verdict, (
        f"Expected adequacy_verdict {verdict}, got {study['adequacy_verdict']}"
    )
    assert study["recommended_annual_contribution_cents"] == recommendation, (
        f"Expected recommended_annual_contribution_cents {recommendation}, "
        f"got {study['recommended_annual_contribution_cents']}"
    )
    if component_count is not None:
        assert study["component_count"] == component_count
    if fully_funded_balance is not None:
        assert study["fully_funded_balance_cents"] == fully_funded_balance
    if percent_funded is not None:
        assert_pct(study["percent_funded"], percent_funded, "percent_funded")
    if min_projected_balance is not None:
        assert study["min_projected_balance_cents"] == min_projected_balance


def assert_unevaluated_study(study: Dict[str, Any]) -> None:
    """A new study is a DRAFT with no evaluation recorded yet."""
    assert study["status"] == "DRAFT"
    assert study["evaluated_method"] is None
    assert study["adequacy_verdict"] == ADEQUACY_UNDETERMINED
    assert study["recommended_annual_contribution_cents"] == 0
    assert study["component_count"] == 0
    assert study["fully_funded_balance_cents"] == 0
    assert_pct(study["percent_funded"], 0.00, "percent_funded")
    assert study["min_projected_balance_cents"] == 0


# ─── Assessment schedule waterfall (§3.9) ─────────────


def assert_schedule_waterfall(
    schedule: Dict[str, Any],
    billable_lot_count: int,
    reserve_contribution: int,
    subsidy_offset: int,
    annual_requirement: int,
    per_lot_monthly: int,
    annual_total: int,
    residual: int,
    increase_pct: Optional[float] = None,
    owner_vote_required: Optional[bool] = None,
) -> None:
    assert schedule["billable_lot_count"] == billable_lot_count, (
        f"Expected billable_lot_count {billable_lot_count}, got {schedule['billable_lot_count']}"
    )
    assert schedule["reserve_contribution_cents"] == reserve_contribution, (
        f"Expected reserve_contribution_cents {reserve_contribution}, "
        f"got {schedule['reserve_contribution_cents']}"
    )
    assert schedule["subsidy_offset_cents"] == subsidy_offset, (
        f"Expected subsidy_offset_cents {subsidy_offset}, got {schedule['subsidy_offset_cents']}"
    )
    assert schedule["annual_requirement_cents"] == annual_requirement, (
        f"Expected annual_requirement_cents {annual_requirement}, "
        f"got {schedule['annual_requirement_cents']}"
    )
    assert schedule["per_lot_monthly_assessment_cents"] == per_lot_monthly, (
        f"Expected per_lot_monthly_assessment_cents {per_lot_monthly}, "
        f"got {schedule['per_lot_monthly_assessment_cents']}"
    )
    assert schedule["annual_budget_total_cents"] == annual_total, (
        f"Expected annual_budget_total_cents {annual_total}, "
        f"got {schedule['annual_budget_total_cents']}"
    )
    assert schedule["residual_cents"] == residual, (
        f"Expected residual_cents {residual}, got {schedule['residual_cents']}"
    )
    assert (
        schedule["annual_budget_total_cents"]
        == schedule["per_lot_monthly_assessment_cents"]
        * schedule["billable_lot_count"]
        * MONTHS_PER_YEAR
    ), "annual_budget_total_cents is the per-lot figure multiplied back up"
    assert (
        schedule["residual_cents"]
        == schedule["annual_budget_total_cents"] - schedule["annual_requirement_cents"]
    ), "residual_cents is annual_budget_total_cents less annual_requirement_cents"
    if increase_pct is not None:
        assert_pct(schedule["increase_pct_vs_prior"], increase_pct, "increase_pct_vs_prior")
    if owner_vote_required is not None:
        assert schedule["owner_vote_required"] is owner_vote_required, (
            f"Expected owner_vote_required {owner_vote_required}, "
            f"got {schedule['owner_vote_required']}"
        )


# ─── Statutory clocks (§2.5) ──────────────────────────


def _normalise_instant(value: str) -> str:
    """Drop a zero fractional part so ``...T00:00:00.000Z`` compares equal to ``...T00:00:00Z``."""
    return value.replace(".000Z", "Z")


def assert_instant(actual: Any, expected: str, field_name: str = "instant") -> None:
    assert actual is not None, f"{field_name} must be set"
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"Expected {field_name} {expected}, got {actual}"
    )


def assert_cancellation_window(contract: Dict[str, Any], certified_at: str) -> None:
    """cancellation_window_end is trigger_certified_at plus ninety days."""
    from datetime import datetime, timedelta

    base = datetime.strptime(certified_at, "%Y-%m-%dT%H:%M:%SZ")
    expected = (base + timedelta(days=CANCELLATION_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    actual = contract["cancellation_window_end"]
    assert actual is not None, "cancellation_window_end must be set on a CANCELLABLE contract"
    assert actual.replace(".000Z", "Z") == expected, (
        f"cancellation_window_end must be trigger_certified_at plus "
        f"{CANCELLATION_WINDOW_DAYS} days ({expected}), got {actual}"
    )
