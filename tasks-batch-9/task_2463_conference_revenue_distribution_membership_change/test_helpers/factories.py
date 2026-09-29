"""Payload factories: valid-by-default request bodies, overridable per test."""

from typing import Any, Dict

from .constants import TEST_DEFAULTS, THRESHOLDS
from .types import (
    ActionType,
    AdmissionPath,
    AllocationMethod,
    AuditOpinion,
    BallotChoice,
    EventTier,
    PoolType,
    RunVariant,
    TransferType,
)


def make_conference_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["CONFERENCE_NAME"],
        "fiscal_year_start_month": THRESHOLDS["DEFAULT_FISCAL_YEAR_START_MONTH"],
        "current_fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "unit_value_cents": THRESHOLDS["DEFAULT_UNIT_VALUE_CENTS"],
        "phase_schedule_years": THRESHOLDS["DEFAULT_PHASE_SCHEDULE_YEARS"],
    }
    payload.update(overrides)
    return payload


def make_venue_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Northfield Dome",
        "city": "Northfield",
        "seating_capacity": 60000,
        "concurrent_event_capacity": 1,
    }
    payload.update(overrides)
    return payload


def make_member_payload(
    conference_id: str, home_venue_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "name": "North State University",
        "institution_code": "NOR",
        "admission_path": AdmissionPath.CHARTER.value,
        "home_venue_id": home_venue_id,
        "grant_of_rights_through_fiscal_year": TEST_DEFAULTS[
            "GOR_THROUGH_FISCAL_YEAR"
        ],
    }
    payload.update(overrides)
    return payload


def make_entry_fee_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents, "reference": "wire-1"}
    payload.update(overrides)
    return payload


def make_member_update_payload(
    expected_member_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_member_version": expected_member_version}
    payload.update(overrides)
    return payload


def make_withdrawal_notice_payload(
    withdrawal_effective_fiscal_year: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "withdrawal_effective_fiscal_year": withdrawal_effective_fiscal_year,
        "notice_days": 1095,
        "reason": "Conference realignment",
    }
    payload.update(overrides)
    return payload


def make_reserve_transfer_payload(
    amount_cents: int, expected_conference_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transfer_type": TransferType.CONTRIBUTION.value,
        "amount_cents": amount_cents,
        "expected_conference_version": expected_conference_version,
        "memo": "Reserve funding",
    }
    payload.update(overrides)
    return payload


def make_budget_proposal_payload(conference_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "proposed_operating_expense_cents": TEST_DEFAULTS["OPERATING_EXPENSE_CENTS"],
        "proposed_governance_expense_cents": TEST_DEFAULTS["GOVERNANCE_EXPENSE_CENTS"],
        "note": "Annual operating plan",
    }
    payload.update(overrides)
    return payload


def make_budget_ballot_payload(
    member_id: str, choice: str = BallotChoice.FOR.value, **overrides: Any
) -> Dict[str, Any]:
    """Budget ballots carry no expected-version field."""
    payload: Dict[str, Any] = {"member_id": member_id, "choice": choice}
    payload.update(overrides)
    return payload


def make_membership_action_payload(
    conference_id: str, member_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "member_id": member_id,
        "action_type": ActionType.ADMIT.value,
        "effective_fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"] + 1,
        "entry_fee_cents": 0,
        "rationale": "Footprint expansion",
    }
    payload.update(overrides)
    return payload


def make_action_ballot_payload(
    member_id: str,
    expected_action_version: int,
    choice: str = BallotChoice.FOR.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "choice": choice,
        "expected_action_version": expected_action_version,
    }
    payload.update(overrides)
    return payload


def make_action_amend_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "effective_fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"] + 2,
        "rationale": "Revised terms",
    }
    payload.update(overrides)
    return payload


def make_revenue_pool_payload(conference_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "pool_type": PoolType.MEDIA_RIGHTS.value,
        "allocation_method": AllocationMethod.APPEARANCE_PERFORMANCE_WEIGHTED.value,
        "gross_revenue_cents": TEST_DEFAULTS["MEDIA_POOL_GROSS_CENTS"],
        "estimated_expense_cents": TEST_DEFAULTS["MEDIA_POOL_ESTIMATED_EXPENSE_CENTS"],
    }
    payload.update(overrides)
    return payload


def make_distribution_run_payload(
    expected_pool_version: int,
    variant: str = RunVariant.PROVISIONAL.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "variant": variant,
        "expected_pool_version": expected_pool_version,
        "memo": "Distribution run",
    }
    payload.update(overrides)
    return payload


def make_bowl_appearance_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "event_name": "Prairie Bowl",
        "event_tier": EventTier.TOURNAMENT.value,
        "payout_cents": 12_000_000,
        "submitted_expense_cents": 9_500_000,
        "travel_miles": 1400,
        "units_claimed": 2,
    }
    payload.update(overrides)
    return payload


def make_bowl_resubmit_payload(
    submitted_expense_cents: int, travel_miles: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "submitted_expense_cents": submitted_expense_cents,
        "travel_miles": travel_miles,
    }
    payload.update(overrides)
    return payload


def make_protected_rivalry_payload(
    conference_id: str, member_a_id: str, member_b_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "member_a_id": member_a_id,
        "member_b_id": member_b_id,
        "required_annual_meetings": 1,
        "label": "Prairie Trophy",
    }
    payload.update(overrides)
    return payload


def make_schedule_game_payload(
    conference_id: str,
    home_member_id: str,
    away_member_id: str,
    venue_id: str,
    game_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "home_member_id": home_member_id,
        "away_member_id": away_member_id,
        "venue_id": venue_id,
        "game_date": game_date,
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "media_designated": True,
    }
    payload.update(overrides)
    return payload


def make_championship_event_payload(
    conference_id: str,
    venue_id: str,
    host_member_id: str,
    revenue_pool_id: str,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "venue_id": venue_id,
        "host_member_id": host_member_id,
        "revenue_pool_id": revenue_pool_id,
        "sport": "BASKETBALL",
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def make_event_settlement_payload(
    ticket_revenue_cents: int,
    sponsorship_revenue_cents: int,
    event_expense_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ticket_revenue_cents": ticket_revenue_cents,
        "sponsorship_revenue_cents": sponsorship_revenue_cents,
        "event_expense_cents": event_expense_cents,
    }
    payload.update(overrides)
    return payload


def make_audit_report_payload(
    conference_id: str, distribution_run_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conference_id": conference_id,
        "distribution_run_id": distribution_run_id,
        "fiscal_year": THRESHOLDS["DEFAULT_CURRENT_FISCAL_YEAR"],
        "opinion": AuditOpinion.UNQUALIFIED.value,
        "note": "Cent conservation verified",
    }
    payload.update(overrides)
    return payload
