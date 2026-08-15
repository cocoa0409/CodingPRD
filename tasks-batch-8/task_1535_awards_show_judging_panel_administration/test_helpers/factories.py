"""Payload factories — one per creatable resource, input fields only (PRD §3/§4).

Each factory emits the canonical valid payload used across the suite; tests
override the specific fields under examination via **overrides.
"""
from .constants import (
    DEFAULT_ACK_WINDOW_HOURS,
    DEFAULT_GO_LIVE_LEAD_MINUTES,
    DEFAULT_MAX_APPEALS_PER_ENTRY,
    EARLY_FEE_CENTS,
    ELIGIBILITY_END,
    ELIGIBILITY_START,
    LATE_FEE_CENTS,
    R1_WINDOW,
    STANDARD_FEE_CENTS,
    STANDARD_RUBRIC,
    T_CEREMONY,
    T_CEREMONY_END,
    T_EARLY_FEE_END,
    T_SUBMISSION_CLOSE,
    T_SUBMISSION_OPEN,
    WORK_COMPLETED,
)


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_season_payload(include_optional: bool = True, **overrides) -> dict:
    """Season creation payload. ``include_optional=False`` strips every field
    the PRD marks optional so server-side defaults can be observed."""
    payload = {
        "code": "GALA-2026",
        "title": "Gala 2026",
        "submission_opens_at": T_SUBMISSION_OPEN,
        "early_fee_ends_at": T_EARLY_FEE_END,
        "submission_closes_at": T_SUBMISSION_CLOSE,
        "eligibility_window_start": ELIGIBILITY_START,
        "eligibility_window_end": ELIGIBILITY_END,
    }
    if include_optional:
        payload.update(
            {
                "ceremony_scheduled_at": T_CEREMONY,
                "refund_policy": "FLAT_FEE",
                "ack_window_hours": DEFAULT_ACK_WINDOW_HOURS,
                "go_live_lead_minutes": DEFAULT_GO_LIVE_LEAD_MINUTES,
                "max_appeals_per_entry": DEFAULT_MAX_APPEALS_PER_ENTRY,
            }
        )
    payload.update(overrides)
    return payload


def create_category_payload(**overrides) -> dict:
    payload = {
        "code": "BEST_PICTURE",
        "name": "Best Picture",
        "min_materials": 1,
        "max_entries_per_entrant": 3,
        "panel_size": 3,
        "finalist_slots": 1,
        "scoring_rubric": [dict(criterion) for criterion in STANDARD_RUBRIC],
        "early_fee_cents": EARLY_FEE_CENTS,
        "standard_fee_cents": STANDARD_FEE_CENTS,
        "late_fee_cents": LATE_FEE_CENTS,
    }
    payload.update(overrides)
    return payload


def create_entrant_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Entrant 1",
        "contact_email": "e1@x.com",
        "country_code": "US",
    }
    payload.update(overrides)
    return payload


def create_entry_payload(**overrides) -> dict:
    payload = {
        "entrant_id": None,  # caller must supply
        "title": "Work 1",
        "work_completed_at": WORK_COMPLETED,
    }
    payload.update(overrides)
    return payload


def create_material_payload(**overrides) -> dict:
    payload = {
        "material_type": "PDF",
        "uri": "s3://material.pdf",
        "file_size_bytes": 1024,
        "checksum_sha256": "0" * 63 + "1",
    }
    payload.update(overrides)
    return payload


def create_judge_payload(**overrides) -> dict:
    payload = {
        "full_name": "Judge 1",
        "email": "j1@x.com",
        "expertise_tags": [],
        "affiliated_entrant_ids": [],
    }
    payload.update(overrides)
    return payload


def create_conflict_payload(**overrides) -> dict:
    payload = {
        "season_id": None,  # caller must supply
        "entrant_id": None,  # caller must supply
        "conflict_type": "FINANCIAL",
        "severity": "HARD",
        "expected_judge_version": None,  # caller must supply
    }
    payload.update(overrides)
    return payload


def create_round_payload(**overrides) -> dict:
    payload = {
        "round_index": 1,
        "scoring_mode": "RAW_RANK",
        "scheduled_window_start": R1_WINDOW[0],
        "scheduled_window_end": R1_WINDOW[1],
        "advance_count": 1,
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(**overrides) -> dict:
    payload = {
        "judge_id": None,  # caller must supply
        "role": "MEMBER",
        "expected_scoring_round_version": None,  # caller must supply
    }
    payload.update(overrides)
    return payload


def create_score_payload(**overrides) -> dict:
    payload = {
        "entry_id": None,  # caller must supply
        "judge_id": None,  # caller must supply
        "criterion_scores": {"CRAFT": 8, "IMPACT": 4},
        "expected_scoring_round_version": None,  # caller must supply
    }
    payload.update(overrides)
    return payload


def create_ceremony_payload(**overrides) -> dict:
    payload = {
        "venue_name": "Grand Hall",
        "starts_at": T_CEREMONY,
        "ends_at": T_CEREMONY_END,
        "rundown": [],  # caller must supply segments
    }
    payload.update(overrides)
    return payload


def create_announcement_payload(**overrides) -> dict:
    payload = {"ceremony_id": None}  # caller must supply
    payload.update(overrides)
    return payload


def create_appeal_payload(**overrides) -> dict:
    payload = {
        "filed_by_entrant_id": None,  # caller must supply
        "grounds": "SCORING_ERROR",
        "narrative": "Scoring irregularity under review.",
    }
    payload.update(overrides)
    return payload
