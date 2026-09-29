"""Domain-specific assertion helpers.

These wrap the repetitive multi-field checks that several tests share.  They
never relax an expectation: each one asserts exact equality on integers and
strings, and compares the fixed-scale decimal fields with an explicit
tolerance that is an order of magnitude tighter than the last significant
digit the contract publishes.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from . import constants as C

# Rates and indices are published with four fractional digits; risk scores and
# money-derived percentages with two.  The tolerances below are tight enough
# that a value rounded to the wrong last digit always fails.
RATE_TOLERANCE = 1e-9
SCORE_TOLERANCE = 1e-9


def assert_rate_4dp(actual: Any, expected: float, label: str = "rate") -> None:
    """Assert a four-decimal rate equals the expected value exactly."""
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"{label}: expected {expected:.4f}, got {actual!r}"
    )


def assert_score_2dp(actual: Any, expected: float, label: str = "score") -> None:
    """Assert a two-decimal score equals the expected value exactly."""
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual!r}"
    )


def _parse_instant(value: Any, label: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits.

    The contract names the clock echo (`current_utc` reports "the new clock
    instant") without pinning how many fractional digits that rendering
    carries, so these helpers compare the instant a response denotes rather
    than its spelling.
    """
    assert isinstance(value, str), f"{label} must be an ISO 8601 string, got {value!r}"
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - surfaces as an assertion
        raise AssertionError(f"{label} is not an ISO 8601 instant: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC renderings denote the same instant."""
    assert _parse_instant(actual, label) == _parse_instant(expected, label), (
        f"{label}: expected the instant {expected}, got {actual!r}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount_cents") -> None:
    """Money is carried as integer cents, so equality must be exact."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_version(resource: Dict[str, Any], expected: int) -> None:
    assert resource.get("version") == expected, (
        f"version: expected {expected}, got {resource.get('version')!r}"
    )


def assert_no_version_field(body: Dict[str, Any]) -> None:
    """An immutable audit row carries neither a version nor an update stamp."""
    assert "version" not in body, f"unexpected version field: {body.get('version')!r}"
    assert "updated_at" not in body, (
        f"unexpected updated_at field: {body.get('updated_at')!r}"
    )


def assert_fresh_agency_defaults(agency: Dict[str, Any]) -> None:
    """A newly registered agency starts on both dimensions' initial states."""
    assert agency["vetting_state"] == C.VETTING_DRAFT
    assert agency["compliance_posture"] == C.POSTURE_GOOD_STANDING
    assert_score_2dp(agency["rolling_risk_score"], 0.00, "rolling_risk_score")
    assert_score_2dp(agency["lifetime_risk_score"], 0.00, "lifetime_risk_score")
    assert agency["confirmed_incident_count"] == 0
    assert agency["reviewed_document_count"] == 0
    assert agency["confirmed_fraud_document_count"] == 0
    assert_cents(agency["net_earned_commission_cents"], 0, "net_earned_commission_cents")
    assert_cents(agency["clawback_liability_cents"], 0, "clawback_liability_cents")
    assert agency["current_tier"] == C.TIER_UNRATED
    assert agency.get("last_posture_reason") is None


def assert_empty_diligence_checklist(agency: Dict[str, Any]) -> None:
    """The four checklist fields default to their negative values."""
    assert agency["ownership_disclosed"] is False
    assert agency["beneficial_owner_count"] == 0
    assert agency["sanctions_screen_passed"] is False
    assert agency["reference_check_count"] == 0


def assert_occupancy(
    occupancy: Dict[str, Any],
    country_code: str,
    at_date: str,
    exclusive_active_count: int,
    non_exclusive_active_count: int,
    exclusive_cooloff_until: Optional[str],
    exclusive_slot_available: bool,
) -> None:
    assert occupancy["country_code"] == country_code
    assert occupancy["at_date"] == at_date
    assert occupancy["exclusive_active_count"] == exclusive_active_count, (
        f"exclusive_active_count: expected {exclusive_active_count}, "
        f"got {occupancy['exclusive_active_count']!r}"
    )
    assert occupancy["non_exclusive_active_count"] == non_exclusive_active_count, (
        f"non_exclusive_active_count: expected {non_exclusive_active_count}, "
        f"got {occupancy['non_exclusive_active_count']!r}"
    )
    assert occupancy["exclusive_cooloff_until"] == exclusive_cooloff_until, (
        f"exclusive_cooloff_until: expected {exclusive_cooloff_until!r}, "
        f"got {occupancy['exclusive_cooloff_until']!r}"
    )
    assert occupancy["exclusive_slot_available"] is exclusive_slot_available


def assert_projection(
    projection: Dict[str, Any],
    provisional_projection_cents: int,
    final_net_cents: int,
    variant_delta_cents: int,
    accrued_entry_count: int,
    clawback_entry_count: int,
) -> None:
    assert_cents(
        projection["provisional_projection_cents"],
        provisional_projection_cents,
        "provisional_projection_cents",
    )
    assert_cents(projection["final_net_cents"], final_net_cents, "final_net_cents")
    assert_cents(
        projection["variant_delta_cents"], variant_delta_cents, "variant_delta_cents"
    )
    assert projection["accrued_entry_count"] == accrued_entry_count
    assert projection["clawback_entry_count"] == clawback_entry_count


def assert_risk_profile(
    profile: Dict[str, Any],
    rolling_risk_score: float,
    lifetime_risk_score: float,
    lifetime_minus_rolling_delta: float,
    confirmed_incident_count: int,
    reviewed_document_count: int,
    confirmed_fraud_document_count: int,
    posture_band: str,
) -> None:
    assert_score_2dp(profile["rolling_risk_score"], rolling_risk_score, "rolling")
    assert_score_2dp(profile["lifetime_risk_score"], lifetime_risk_score, "lifetime")
    assert_score_2dp(
        profile["lifetime_minus_rolling_delta"],
        lifetime_minus_rolling_delta,
        "lifetime_minus_rolling_delta",
    )
    assert profile["confirmed_incident_count"] == confirmed_incident_count
    assert profile["reviewed_document_count"] == reviewed_document_count
    assert profile["confirmed_fraud_document_count"] == confirmed_fraud_document_count
    assert profile["posture_band"] == posture_band


def assert_accrual_entry(
    entry: Dict[str, Any],
    milestone: str,
    tier_snapshot: str,
    effective_bps: int,
    amount_cents: int,
    state: str = C.ENTRY_ACCRUED,
) -> None:
    assert entry["kind"] == C.ENTRY_KIND_ACCRUAL
    assert entry["milestone"] == milestone
    assert entry["tier_snapshot"] == tier_snapshot, (
        f"tier_snapshot for {milestone}: expected {tier_snapshot}, "
        f"got {entry['tier_snapshot']!r}"
    )
    assert entry["effective_bps"] == effective_bps, (
        f"effective_bps for {milestone}: expected {effective_bps}, "
        f"got {entry['effective_bps']!r}"
    )
    assert_cents(entry["amount_cents"], amount_cents, f"amount_cents for {milestone}")
    assert entry["state"] == state


def entries_by_milestone(entries: List[Dict[str, Any]], kind: str) -> Dict[str, Dict]:
    """Index ledger rows of one kind by their milestone."""
    return {e["milestone"]: e for e in entries if e["kind"] == kind}


def one_entry(
    entries: List[Dict[str, Any]], kind: str, milestone: str
) -> Dict[str, Any]:
    """Return the single row of the given kind and milestone, or fail loudly."""
    matches = [e for e in entries if e["kind"] == kind and e["milestone"] == milestone]
    assert len(matches) == 1, (
        f"expected exactly one {kind} row for {milestone}, found {len(matches)}"
    )
    return matches[0]


def assert_sweep_counts(
    result: Dict[str, Any],
    current_utc: str,
    expired_contract_count: int,
    expired_assignment_count: int,
    expired_certification_count: int,
    risk_recomputed_agency_count: int,
) -> None:
    assert_instant(result["current_utc"], current_utc, "current_utc")
    assert result["expired_contract_count"] == expired_contract_count
    assert result["expired_assignment_count"] == expired_assignment_count
    assert result["expired_certification_count"] == expired_certification_count
    assert result["risk_recomputed_agency_count"] == risk_recomputed_agency_count
