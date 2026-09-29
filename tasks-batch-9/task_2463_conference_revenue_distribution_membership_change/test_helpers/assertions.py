"""Domain assertion helpers built on top of the framework validators."""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import LIGHT_RESOURCE_FORBIDDEN_FIELDS


def assert_identity_fields(resource: Dict[str, Any]) -> None:
    """Every resource carries a UUID ``id`` and an ISO-8601 ``created_at``."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource.get('id')!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO-8601: {resource.get('created_at')!r}"


def assert_versioned_resource(resource: Dict[str, Any]) -> None:
    """A resource that carries the full identity block: created_at, updated_at, version."""
    assert_identity_fields(resource)
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not ISO-8601: {resource.get('updated_at')!r}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version must start at 1"


def assert_light_resource(resource: Dict[str, Any]) -> None:
    """A distribution line, a postseason unit and a ballot carry only id and created_at."""
    assert_identity_fields(resource)
    for field in LIGHT_RESOURCE_FORBIDDEN_FIELDS:
        assert field not in resource, (
            f"light resource must not expose {field!r}: {sorted(resource)}"
        )


def assert_fields_equal(resource: Dict[str, Any], **expected: Any) -> None:
    """Assert each named field of ``resource`` equals the expected value."""
    for field, value in expected.items():
        assert field in resource, f"missing field {field!r} in {sorted(resource)}"
        assert resource[field] == value, (
            f"{field}: expected {value!r}, got {resource[field]!r}"
        )


def assert_same_instant(actual: Any, expected: str) -> None:
    """Assert a client-supplied instant round-trips as the same UTC instant.

    The PRD pins a three-fractional-digit rendering only for the housekeeping
    ``created_at`` / ``updated_at`` properties (§2.5); for an instant the client
    itself supplied (a game's ``game_date``, an event's occupancy window) it
    requires only that the value parse as an ISO 8601 UTC timestamp (§2.8), so
    the comparison is on the instant rather than on its rendering.
    """
    assert isinstance(actual, str), f"expected an ISO 8601 instant, got {actual!r}"
    assert datetime.fromisoformat(actual.replace("Z", "+00:00")) == datetime.fromisoformat(
        expected.replace("Z", "+00:00")
    ), f"expected instant {expected!r}, got {actual!r}"


def assert_posture(
    conference: Dict[str, Any], posture: str, funded_ratio_bps: int
) -> None:
    assert_fields_equal(
        conference, reserve_posture=posture, funded_ratio_bps=funded_ratio_bps
    )


def lines_by_member(lines: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a run's lines by the member they credit."""
    return {line["member_id"]: line for line in lines}


def assert_line(line: Dict[str, Any], **expected: Any) -> None:
    """Assert a distribution line's arithmetic, and its shape while we are here."""
    assert_light_resource(line)
    assert_fields_equal(line, **expected)


def assert_cents_conserved(distributable_cents: int, lines: List[Dict[str, Any]]) -> None:
    """The floored shares plus the dealt remainder cents exhaust the distributable amount."""
    total_gross = sum(line["gross_share_cents"] for line in lines)
    assert total_gross == distributable_cents, (
        f"gross shares sum to {total_gross}, expected {distributable_cents}"
    )


def assert_reconciliation(
    reconciliation: Dict[str, Any],
    net_pool_cents: int,
    reserve_draw_cents: int,
    total_net_payable_cents: int,
    total_withheld_cents: int,
    total_governance_fee_cents: int,
    total_gor_offset_cents: int,
    reconciliation_delta_cents: int = 0,
) -> None:
    assert_fields_equal(
        reconciliation,
        net_pool_cents=net_pool_cents,
        reserve_draw_cents=reserve_draw_cents,
        total_net_payable_cents=total_net_payable_cents,
        total_withheld_cents=total_withheld_cents,
        total_governance_fee_cents=total_governance_fee_cents,
        total_gor_offset_cents=total_gor_offset_cents,
        reconciliation_delta_cents=reconciliation_delta_cents,
    )
    identity = net_pool_cents - (
        reserve_draw_cents
        + total_net_payable_cents
        + total_withheld_cents
        + total_governance_fee_cents
        + total_gor_offset_cents
    )
    assert identity == reconciliation_delta_cents, (
        f"identity recomputes to {identity}, response reports "
        f"{reconciliation_delta_cents}"
    )


def assert_tally(
    record: Dict[str, Any],
    eligible_weight_bps: int,
    cast_weight_bps: int,
    for_weight_bps: int,
    against_weight_bps: int,
    quorum_met: bool,
    approval_ratio_bps: int,
    status: Optional[str] = None,
) -> None:
    expected: Dict[str, Any] = {
        "eligible_weight_bps": eligible_weight_bps,
        "cast_weight_bps": cast_weight_bps,
        "for_weight_bps": for_weight_bps,
        "against_weight_bps": against_weight_bps,
        "quorum_met": quorum_met,
        "approval_ratio_bps": approval_ratio_bps,
    }
    if status is not None:
        expected["status"] = status
    assert_fields_equal(record, **expected)


def assert_reimbursement(
    appearance: Dict[str, Any],
    allowable_expense_cents: int,
    travel_allowance_cents: int,
    reimbursement_ceiling_cents: int,
    reimbursed_cents: int,
    residual_to_pool_cents: int,
) -> None:
    assert_fields_equal(
        appearance,
        allowable_expense_cents=allowable_expense_cents,
        travel_allowance_cents=travel_allowance_cents,
        reimbursement_ceiling_cents=reimbursement_ceiling_cents,
        reimbursed_cents=reimbursed_cents,
        residual_to_pool_cents=residual_to_pool_cents,
    )
    assert reimbursed_cents == appearance["payout_cents"] - residual_to_pool_cents, (
        "residual must be the payout minus the reimbursement"
    )


def assert_exit_assessment(
    settlement: Dict[str, Any],
    notice_multiplier_bps: int,
    base_assessment_cents: int,
    surcharge_bracket_bps: int,
    surcharge_cents: int,
    exit_settlement_total_cents: int,
    exit_settlement_paid_cents: int = 0,
) -> None:
    assert_fields_equal(
        settlement,
        notice_multiplier_bps=notice_multiplier_bps,
        base_assessment_cents=base_assessment_cents,
        surcharge_bracket_bps=surcharge_bracket_bps,
        surcharge_cents=surcharge_cents,
        exit_settlement_total_cents=exit_settlement_total_cents,
        exit_settlement_paid_cents=exit_settlement_paid_cents,
    )


def assert_compliance_breakdown(
    breakdown: Dict[str, Any],
    unmet_rivalry_count: int,
    travel_partner_gap_count: int,
    home_game_count: int,
    away_game_count: int,
    schedule_compliance_score: int,
) -> None:
    assert_fields_equal(
        breakdown,
        unmet_rivalry_count=unmet_rivalry_count,
        travel_partner_gap_count=travel_partner_gap_count,
        home_game_count=home_game_count,
        away_game_count=away_game_count,
        schedule_compliance_score=schedule_compliance_score,
    )


def assert_valuation(
    valuation: Dict[str, Any],
    variant: str,
    window_start_fiscal_year: int,
    window_end_fiscal_year: int,
    validated_unit_count: int,
    valuation_cents: int,
) -> None:
    assert_fields_equal(
        valuation,
        variant=variant,
        window_start_fiscal_year=window_start_fiscal_year,
        window_end_fiscal_year=window_end_fiscal_year,
        validated_unit_count=validated_unit_count,
        valuation_cents=valuation_cents,
    )


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert_fields_equal(
        meta, limit=limit, offset=offset, total_count=total_count, has_more=has_more
    )
