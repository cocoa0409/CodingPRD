"""Payload factories — one per write endpoint, input fields only.

Every factory returns a plain dict and accepts `**overrides` so a test can move
exactly the field under assertion and leave everything else pinned.
"""

from typing import Any, Dict, List

from .constants import (
    COLD_START_UTC,
    COMPANIES,
    DEFAULT_MEETING_DATE,
    EXECUTIVES,
    METRICS,
    PROGRAM_MIX_15_25_60,
    REASONS,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str = COLD_START_UTC) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
def create_company_payload(template: str = "ACME", **overrides) -> Dict[str, Any]:
    """Body for company registration, seeded from the canonical catalogue.

    `template` names the catalogue row to copy; it is not itself a payload
    field, so `ticker=` may be overridden freely (a test that needs two
    differently-tickered companies off the same catalogue row does exactly
    that).
    """
    payload = dict(COMPANIES[template])
    payload.update(overrides)
    return payload


def market_data_payload(**overrides) -> Dict[str, Any]:
    """Body for a market-data refresh; every field is optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Executive
# ---------------------------------------------------------------------------
def create_executive_payload(profile: str = "CEO", **overrides) -> Dict[str, Any]:
    payload = dict(EXECUTIVES[profile])
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PeerGroup / PeerGroupMember
# ---------------------------------------------------------------------------
def create_peer_group_payload(
    issuer_company_id: str, benchmark_basis: str = "RAW_MEDIAN", fiscal_year: int = 2026, **overrides
) -> Dict[str, Any]:
    payload = {
        "issuer_company_id": issuer_company_id,
        "fiscal_year": fiscal_year,
        "benchmark_basis": benchmark_basis,
    }
    payload.update(overrides)
    return payload


def add_member_payload(
    peer_company_id: str,
    expected_peer_group_version: int,
    inclusion_reason: str = "SIZE_MATCH",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "peer_company_id": peer_company_id,
        "inclusion_reason": inclusion_reason,
        "expected_peer_group_version": expected_peer_group_version,
    }
    payload.update(overrides)
    return payload


def exclude_member_payload(exclusion_reason: str = REASONS["exclusion"], **overrides):
    payload = {"exclusion_reason": exclusion_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PayProgram
# ---------------------------------------------------------------------------
def create_pay_program_payload(
    issuer_company_id: str,
    peer_group_id: str,
    ceo_executive_id: str,
    fiscal_year: int = 2026,
    meeting_date: str = DEFAULT_MEETING_DATE,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "issuer_company_id": issuer_company_id,
        "peer_group_id": peer_group_id,
        "ceo_executive_id": ceo_executive_id,
        "fiscal_year": fiscal_year,
        "meeting_date": meeting_date,
    }
    payload.update(PROGRAM_MIX_15_25_60)
    payload.update(overrides)
    return payload


def mix_reallocation_payload(
    from_component: str,
    to_component: str,
    points: float,
    expected_pay_program_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "from_component": from_component,
        "to_component": to_component,
        "points": points,
        "expected_pay_program_version": expected_pay_program_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IncentiveMetric
# ---------------------------------------------------------------------------
def create_incentive_metric_payload(curve: str = "ADJ_EPS_LINEAR", **overrides) -> Dict[str, Any]:
    payload = dict(METRICS[curve])
    payload.update(overrides)
    return payload


def adjustment_payload(
    expected_incentive_metric_version: int,
    result_adjustment_reason: str = REASONS["goal_adjustment"],
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "result_adjustment_reason": result_adjustment_reason,
        "expected_incentive_metric_version": expected_incentive_metric_version,
    }
    payload.update(overrides)
    return payload


def metric_result_payload(as_reported_value: float, **overrides) -> Dict[str, Any]:
    payload = {"as_reported_value": as_reported_value}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PayoutAward
# ---------------------------------------------------------------------------
def create_payout_award_payload(
    executive_id: str, vehicle: str = "ANNUAL_INCENTIVE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"executive_id": executive_id, "vehicle": vehicle}
    if vehicle in ("LONG_TERM_PSU", "RSU"):
        payload["units_granted"] = 100000
        payload["grant_price_usd"] = 50.00
    payload.update(overrides)
    return payload


def settlement_payload(
    disposition: str = "VEST", settlement_date: str = "2026-09-30T00:00:00Z", **overrides
) -> Dict[str, Any]:
    payload = {"disposition": disposition, "settlement_date": settlement_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CdaDraft
# ---------------------------------------------------------------------------
def create_cda_draft_payload(
    section_code: str = "CD_AND_A",
    word_count: int = 2000,
    required_tables_included: bool = True,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "section_code": section_code,
        "word_count": word_count,
        "required_tables_included": required_tables_included,
    }
    payload.update(overrides)
    return payload


def submit_review_payload(**overrides) -> Dict[str, Any]:
    """Both fields are optional on a review submission."""
    return dict(overrides)


def request_revision_payload(feedback_summary: str = REASONS["cda_feedback"], **overrides):
    payload = {"feedback_summary": feedback_summary}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ProxyAdvisorScreen
# ---------------------------------------------------------------------------
def create_screen_payload(advisor: str = "ISS", **overrides) -> Dict[str, Any]:
    payload = {"advisor": advisor}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OutreachEngagement
# ---------------------------------------------------------------------------
def create_engagement_payload(
    investor_name: str = "BlackRock",
    ownership_pct: float = 20.00,
    channel: str = "MEETING",
    investor_key: str = None,
    **overrides,
) -> Dict[str, Any]:
    """The investor key is the trimmed, upper-cased investor name."""
    payload = {
        "investor_name": investor_name,
        "investor_key": investor_key if investor_key is not None else investor_name.strip().upper(),
        "ownership_pct": ownership_pct,
        "channel": channel,
    }
    payload.update(overrides)
    return payload


def schedule_engagement_payload(window_start: str, window_end: str, **overrides) -> Dict[str, Any]:
    payload = {"window_start": window_start, "window_end": window_end}
    payload.update(overrides)
    return payload


def hold_engagement_payload(
    feedback_position: str = "SUPPORTIVE", **overrides
) -> Dict[str, Any]:
    payload = {"feedback_position": feedback_position}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Say-on-pay vote / remediation
# ---------------------------------------------------------------------------
def vote_certification_payload(
    votes_for: int, votes_against: int, abstentions: int = 0, **overrides
) -> Dict[str, Any]:
    payload = {
        "votes_for": votes_for,
        "votes_against": votes_against,
        "abstentions": abstentions,
    }
    payload.update(overrides)
    return payload


def remediation_payload(feedback_summary: str = REASONS["remediation"], **overrides):
    payload = {"feedback_summary": feedback_summary}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RestatementEvent / ClawbackDetermination
# ---------------------------------------------------------------------------
def create_restatement_event_payload(
    restatement_date: str = "2027-03-01T00:00:00Z",
    lookback_start: str = "2026-01-01T00:00:00Z",
    lookback_end: str = "2026-12-31T23:59:59Z",
    accounting_reason: str = REASONS["restatement"],
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "restatement_date": restatement_date,
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "accounting_reason": accounting_reason,
    }
    payload.update(overrides)
    return payload


def analyze_payload(restated_metric_results: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
    payload = {"restated_metric_results": restated_metric_results}
    payload.update(overrides)
    return payload


def restated_metric_result(incentive_metric_id: str, restated_achieved_value: float) -> Dict[str, Any]:
    return {
        "incentive_metric_id": incentive_metric_id,
        "restated_achieved_value": restated_achieved_value,
    }


def reverse_recovery_payload(reversal_reason: str = REASONS["reversal"], **overrides):
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload
