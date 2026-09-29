"""Shape and invariant assertions.

One ``assert_<entity>`` per entity plus a handful of cross-entity invariant
checkers for the conserved quantities and the casting-posture derivation.
"""

from typing import Optional

import pytest

from .constants import (
    FROZEN_INCIDENT_COUNT,
    RESTRICTED_UTILISATION_DENOMINATOR,
    RESTRICTED_UTILISATION_NUMERATOR,
)

# Every mutable record carries these four (PRD §2.4).
VERSIONED_FIELDS = ("id", "created_at", "updated_at", "version")

# Append-only evidence carries only these two (PRD §2.4).
APPEND_ONLY_FIELDS = ("id", "created_at")


def _require(data: dict, fields, label: str) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"{label} is missing field(s) {missing}: {data}"


def assert_versioned_envelope(data: dict, label: str) -> None:
    """A mutable record exposes id, created_at, updated_at and version."""
    _require(data, VERSIONED_FIELDS, label)
    assert isinstance(data["version"], int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_envelope(data: dict, label: str) -> None:
    """An append-only record carries id + created_at and nothing versioned."""
    _require(data, APPEND_ONLY_FIELDS, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at: {data}"
    assert "version" not in data, f"{label} must not carry version: {data}"


# ------------------------------------------------------------------ entities


def assert_production(data: dict) -> dict:
    _require(
        data,
        (
            "title",
            "format_type",
            "jurisdiction_code",
            "season_number",
            "episode_order",
            "photography_start_utc",
            "photography_end_utc",
            "stipend_pool_cents",
            "stipend_committed_cents",
            "welfare_budget_cents",
            "welfare_committed_cents",
            "trust_escrow_balance_cents",
            "duty_of_care_tier",
            "welfare_incident_count",
            "breached_obligation_count",
            "casting_posture",
            "minor_participant_cap",
            "minor_participant_count",
        ),
        "Production",
    )
    assert_versioned_envelope(data, "Production")
    assert data["duty_of_care_tier"] in ("STANDARD", "ENHANCED", "CRITICAL")
    assert data["casting_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    return data


def assert_location(data: dict) -> dict:
    _require(
        data,
        ("name", "state_code", "capacity", "turnaround_buffer_minutes", "filming_permit_number"),
        "Location",
    )
    assert_versioned_envelope(data, "Location")
    return data


def assert_casting_call(data: dict) -> dict:
    _require(
        data,
        (
            "production_id",
            "venue_location_id",
            "channel",
            "min_age",
            "max_age",
            "residency_state_code",
            "open_call_window_start_utc",
            "open_call_window_end_utc",
            "expected_attendance",
            "exclusivity_window_days",
            "status",
            "published_at",
            "closed_reason",
            "screened_pass_count",
        ),
        "CastingCall",
    )
    assert_versioned_envelope(data, "CastingCall")
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    return data


def assert_applicant(data: dict) -> dict:
    _require(
        data,
        (
            "casting_call_id",
            "legal_name",
            "date_of_birth",
            "residency_state_code",
            "guardian_name",
            "is_minor",
            "screening_status",
            "medical_status",
            "psych_eval_required",
            "provisional_risk_score",
            "final_risk_score",
            "enhanced_support_required",
        ),
        "Applicant",
    )
    assert_versioned_envelope(data, "Applicant")
    assert data["screening_status"] in (
        "SUBMITTED",
        "SCREENING",
        "CLEARED",
        "REJECTED",
        "WITHDRAWN",
        "CAST",
    )
    assert data["medical_status"] in (
        "NOT_STARTED",
        "PENDING",
        "CLEARED",
        "DEFERRED",
        "EXPIRED",
    )
    assert isinstance(data["is_minor"], bool)
    return data


def assert_screening_item(data: dict) -> dict:
    _require(
        data,
        (
            "applicant_id",
            "kind",
            "outcome",
            "severity_flags",
            "conditional_conditions",
            "recorded_by_user_id",
            "recorded_at",
            "expires_at",
        ),
        "ScreeningItem",
    )
    assert_versioned_envelope(data, "ScreeningItem")
    assert data["outcome"] in ("PENDING", "PASS", "CONDITIONAL", "FAIL")
    return data


def assert_minor_protection(data: dict) -> dict:
    _require(
        data,
        (
            "applicant_id",
            "work_permit_number",
            "permit_expires_on",
            "education_hours_scheduled_weekly",
            "trust_deposit_pct",
            "trust_deposited_cents",
            "installment_count",
            "per_installment_cents",
            "status",
        ),
        "MinorProtection",
    )
    assert_versioned_envelope(data, "MinorProtection")
    assert data["status"] in ("INCOMPLETE", "COMPLETE", "LAPSED", "RELEASED")
    return data


def assert_agreement(data: dict) -> dict:
    _require(
        data,
        (
            "applicant_id",
            "production_id",
            "supersedes_agreement_id",
            "status",
            "round_number",
            "exclusivity_window_days",
            "confidentiality_tier",
            "depiction_rights_scope",
            "stipend_structure",
            "base_stipend_cents",
            "episodes_committed",
            "press_appearance_obligation_count",
            "reunion_obligation",
            "provisional_stipend_cents",
            "total_stipend_commitment_cents",
            "last_production_proposer_user_id",
            "executed_by_user_id",
            "executed_at",
            "welfare_hold",
            "void_reason",
        ),
        "ParticipantAgreement",
    )
    assert_versioned_envelope(data, "ParticipantAgreement")
    assert data["status"] in (
        "DRAFTED",
        "SENT",
        "COUNTERED",
        "REVISED",
        "EXECUTED",
        "VOIDED",
    )
    return data


def assert_negotiation_round(data: dict) -> dict:
    """Append-only: no updated_at, no version."""
    _require(
        data,
        (
            "agreement_id",
            "round_number",
            "proposed_by",
            "proposer_user_id",
            "requested_base_stipend_cents",
            "requested_exclusivity_window_days",
            "requested_depiction_rights_scope",
            "disposition",
            "recorded_at",
        ),
        "NegotiationRound",
    )
    assert_append_only_envelope(data, "NegotiationRound")
    assert data["proposed_by"] in ("PRODUCTION", "PARTICIPANT")
    assert data["disposition"] in ("COUNTERED", "REVISED")
    return data


def assert_welfare_protocol(data: dict) -> dict:
    _require(
        data,
        (
            "production_id",
            "kind",
            "coverage_start_utc",
            "coverage_end_utc",
            "cost_cents",
            "carrier_certificate_number",
            "status",
        ),
        "WelfareProtocol",
    )
    assert_versioned_envelope(data, "WelfareProtocol")
    assert data["status"] in ("PLANNED", "ACTIVE", "EXPIRED", "CANCELLED")
    return data


def assert_shoot_block(data: dict) -> dict:
    _require(
        data,
        (
            "production_id",
            "location_id",
            "block_kind",
            "start_utc",
            "end_utc",
            "expected_crowd_headcount",
            "participant_agreement_ids",
            "onset_minor_hours",
            "status",
            "minor_participant_count",
            "covered_head_count",
            "release_coverage_complete",
        ),
        "ShootBlock",
    )
    assert_versioned_envelope(data, "ShootBlock")
    assert data["status"] in ("SCHEDULED", "ROLLING", "WRAPPED", "CANCELLED")
    assert isinstance(data["participant_agreement_ids"], list)
    return data


def assert_release(data: dict) -> dict:
    """Append-only: no updated_at, no version."""
    _require(
        data,
        (
            "shoot_block_id",
            "subject_kind",
            "subject_name",
            "head_count",
            "guardian_signature",
            "disposition",
            "collected_at",
        ),
        "Release",
    )
    assert_append_only_envelope(data, "Release")
    assert data["disposition"] in ("COLLECTED", "REFUSED", "BLURRED_WAIVER")
    return data


def assert_post_obligation(data: dict) -> dict:
    _require(
        data,
        (
            "agreement_id",
            "kind",
            "sequence_ordinal",
            "due_utc",
            "fee_cents",
            "status",
            "fulfilled_at",
        ),
        "PostObligation",
    )
    assert_versioned_envelope(data, "PostObligation")
    assert data["kind"] in ("PRESS_JUNKET", "REUNION_TAPING")
    assert data["status"] in ("SCHEDULED", "FULFILLED", "EXCUSED", "BREACHED")
    return data


def assert_complaint(data: dict) -> dict:
    _require(
        data,
        (
            "agreement_id",
            "category",
            "severity",
            "narrative",
            "status",
            "duty_of_care_breach",
            "aftercare_sessions_authorized",
            "triaged_by_user_id",
            "routed_by_user_id",
            "resolution_note",
        ),
        "Complaint",
    )
    assert_versioned_envelope(data, "Complaint")
    assert data["status"] in (
        "OPEN",
        "TRIAGED",
        "AFTERCARE_ACTIVE",
        "ESCALATED",
        "RESOLVED",
    )
    return data


# ------------------------------------------------------- domain invariants


def assert_money(actual: int, expected: int, label: str = "amount") -> None:
    """Money is integer cents; no tolerance is permitted."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_score(actual: float, expected: float, label: str = "score") -> None:
    """Risk scores are carried to two decimals."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_expected_posture(production: dict) -> None:
    """Re-derive casting_posture from the production's own counters.

    FROZEN wins over RESTRICTED, which wins over OPEN.  The utilisation test is
    the integer cross-multiplication ``committed * 100 >= pool * 90``, and the
    minor clause only fires for a production whose cap is above zero.
    """
    frozen = (
        production["welfare_committed_cents"] > production["welfare_budget_cents"]
        or production["welfare_incident_count"] >= FROZEN_INCIDENT_COUNT
    )
    restricted = (
        production["stipend_committed_cents"] * RESTRICTED_UTILISATION_DENOMINATOR
        >= production["stipend_pool_cents"] * RESTRICTED_UTILISATION_NUMERATOR
    ) or (
        production["minor_participant_cap"] > 0
        and production["minor_participant_count"] >= production["minor_participant_cap"]
    )
    expected = "FROZEN" if frozen else ("RESTRICTED" if restricted else "OPEN")
    assert production["casting_posture"] == expected, (
        f"casting_posture should be {expected} for counters "
        f"stipend_committed_cents={production['stipend_committed_cents']}, "
        f"stipend_pool_cents={production['stipend_pool_cents']}, "
        f"welfare_committed_cents={production['welfare_committed_cents']}, "
        f"welfare_budget_cents={production['welfare_budget_cents']}, "
        f"welfare_incident_count={production['welfare_incident_count']}, "
        f"minor_participant_count={production['minor_participant_count']}/"
        f"{production['minor_participant_cap']}; "
        f"got {production['casting_posture']}"
    )


def assert_conserved(before: int, after: int, delta: int, label: str) -> None:
    """A conserved counter moved by exactly ``delta`` and by nothing else."""
    assert after - before == delta, (
        f"{label} should have moved by exactly {delta} "
        f"(from {before} to {before + delta}); got {after}"
    )


def assert_unchanged(before: dict, after: dict, field: str) -> None:
    assert before[field] == after[field], (
        f"{field} must be unchanged by a rejected call: "
        f"was {before[field]}, now {after[field]}"
    )


def assert_status(data: dict, expected: str, label: str = "record") -> None:
    assert data["status"] == expected, (
        f"{label} status should be {expected}, got {data['status']}"
    )


def assert_version_bumped(before: dict, after: dict, by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version should have advanced by {by} from {before['version']}, "
        f"got {after['version']}"
    )


def assert_ordered_by_created_at(rows: list) -> None:
    """Collections come back in ascending created_at order."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_pagination_meta(
    meta: dict,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    for key in ("total_count", "has_more", "limit", "offset"):
        assert key in meta, f"pagination meta is missing {key}: {meta}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
