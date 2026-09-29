"""Payload factories — one per entity, request-input fields only."""

from typing import Any, Dict, List, Optional

from .constants import RULE_DEFAULTS, TEST_DEFAULTS


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into defaults; a value of ``None`` drops the key."""
    merged = dict(defaults)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


def create_induction_cycle_payload(**overrides) -> dict:
    return _merge(
        {
            "cycle_year": TEST_DEFAULTS["CYCLE_YEAR"],
            "sport_code": TEST_DEFAULTS["SPORT_CODE"],
            "max_inductees": TEST_DEFAULTS["MAX_INDUCTEES"],
            "travel_budget_cents": TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"],
            "escort_pool_size": TEST_DEFAULTS["ESCORT_POOL_SIZE"],
        },
        overrides,
    )


def create_eligibility_rule_payload(**overrides) -> dict:
    return _merge(
        {"category": "PLAYER", "pathway": "MODERN", **RULE_DEFAULTS},
        overrides,
    )


def create_voter_bloc_payload(**overrides) -> dict:
    return _merge(
        {
            "bloc_code": TEST_DEFAULTS["BLOC_CODE"],
            "name": TEST_DEFAULTS["BLOC_NAME"],
            "seat_cap": TEST_DEFAULTS["SEAT_CAP"],
            "min_participation_pct": TEST_DEFAULTS["MIN_PARTICIPATION_PCT"],
        },
        overrides,
    )


def create_candidate_payload(**overrides) -> dict:
    return _merge(
        {
            "full_name": "Test Candidate",
            "category": "PLAYER",
            "retirement_year": 2018,
            "career_seasons": 15,
            "career_metric_value": 3000,
            "is_deceased": False,
        },
        overrides,
    )


def create_elector_payload(bloc_id: str, **overrides) -> dict:
    return _merge(
        {
            "full_name": "Test Elector",
            "bloc_id": bloc_id,
            "credential_expires_on": TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
            "is_screening_member": False,
        },
        overrides,
    )


def create_candidacy_payload(
    cycle_id: str, candidate_id: str, nominated_by_elector_id: str, **overrides
) -> dict:
    return _merge(
        {
            "cycle_id": cycle_id,
            "candidate_id": candidate_id,
            "nominated_by_elector_id": nominated_by_elector_id,
            "pathway": "MODERN",
        },
        overrides,
    )


def create_ballot_payload(cycle_id: str, expected_cycle_version: int, **overrides) -> dict:
    return _merge(
        {
            "cycle_id": cycle_id,
            "opens_at": TEST_DEFAULTS["BALLOT_OPENS_AT"],
            "closes_at": TEST_DEFAULTS["BALLOT_CLOSES_AT"],
            "expected_cycle_version": expected_cycle_version,
        },
        overrides,
    )


def create_vote_submission_payload(
    ballot_id: str,
    selected_slot_ids: Optional[List[str]],
    expected_ballot_version: int,
    **overrides,
) -> dict:
    return _merge(
        {
            "ballot_id": ballot_id,
            "selected_slot_ids": selected_slot_ids,
            "expected_ballot_version": expected_ballot_version,
        },
        overrides,
    )


def create_screening_decision_payload(decision: str, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


def create_audit_decision_payload(decision: str, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


def create_ceremony_payload(**overrides) -> dict:
    return _merge(
        {
            "ceremony_date": TEST_DEFAULTS["CEREMONY_DATE"],
            "ceremony_venue": TEST_DEFAULTS["CEREMONY_VENUE"],
            "travel_budget_cents": TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"],
            "escort_pool_size": TEST_DEFAULTS["ESCORT_POOL_SIZE"],
        },
        overrides,
    )


def create_travel_grant_payload(
    induction_id: str, expected_cycle_version: int, **overrides
) -> dict:
    return _merge(
        {
            "induction_id": induction_id,
            "nights": 3,
            "requested_airfare_cents": 0,
            "expected_cycle_version": expected_cycle_version,
        },
        overrides,
    )


def create_exhibit_case_payload(**overrides) -> dict:
    return _merge(
        {"case_code": "CASE-A", "capacity_artifacts": 10, "changeover_buffer_days": 7},
        overrides,
    )


def create_exhibit_installation_payload(
    induction_id: str, exhibit_case_id: str, **overrides
) -> dict:
    return _merge(
        {
            "induction_id": induction_id,
            "exhibit_case_id": exhibit_case_id,
            "display_starts_on": "2026-11-01T00:00:00Z",
            "display_ends_on": "2026-12-01T00:00:00Z",
            "artifact_count": 2,
        },
        overrides,
    )


def create_artifact_intake_payload(**overrides) -> dict:
    return _merge({"artifact_count": 2}, overrides)
