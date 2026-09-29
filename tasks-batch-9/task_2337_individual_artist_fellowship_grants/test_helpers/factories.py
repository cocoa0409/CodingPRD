"""
Payload factories for the Individual Artist Fellowship Grants API.

Each factory returns a valid request body with sensible domain defaults; pass
keyword overrides to vary one field at a time. Optional fields are only present
when explicitly supplied, so a factory can also be used to exercise the PRD's
declared defaults by simply omitting them.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import ACCEPT_AGREEMENT_VERSION

_email_counter = itertools.count(1)


def unique_email(prefix: str = "person") -> str:
    return f"{prefix}.{next(_email_counter)}@example.org"


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# FellowshipCycle
# ---------------------------------------------------------------------------
def cycle_payload(**overrides) -> Dict[str, Any]:
    """A fiscal-year-2027 cycle whose figures drive the PRD's worked examples."""
    payload: Dict[str, Any] = {
        "name": "FY2027 Individual Artist Fellowships",
        "fiscal_year": 2027,
        "application_open_at": "2026-08-15T00:00:00Z",
        "application_deadline_at": "2026-10-15T23:59:59Z",
        "grant_period_start": "2027-01-01T00:00:00Z",
        "grant_period_end": "2027-12-31T00:00:00Z",
        "total_budget_cents": 6_000_000,
        "base_award_cents": 1_500_000,
        "min_prorated_award_cents": 500_000,
        "residency_min_months": 24,
        "award_blackout_years": 3,
        "proration_policy": "PRORATE",
        "max_review_rounds": 2,
        "acceptance_window_days": 14,
        "appeal_window_days": 30,
        "final_report_due_offset_days": 60,
    }
    payload.update(overrides)
    return _drop_none(payload)


def cycle_payload_required_only(**overrides) -> Dict[str, Any]:
    """Only the required cycle fields, so the five optional defaults apply."""
    payload = cycle_payload()
    for optional in (
        "proration_policy",
        "max_review_rounds",
        "acceptance_window_days",
        "appeal_window_days",
        "final_report_due_offset_days",
    ):
        payload.pop(optional, None)
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# DisciplineCategory
# ---------------------------------------------------------------------------
def discipline_payload(cycle_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "code": "LITERARY_ARTS",
        "alias_prefix": "LIT",
        "allocation_cents": 2_000_000,
        "required_work_sample_count": 2,
        "allowed_media": ["MANUSCRIPT_PAGES", "AUDIO"],
        "required_panel_seats": 5,
        "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
        "max_total_duration_seconds": 600,
        "max_concurrent_panels": 1,
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Artist
# ---------------------------------------------------------------------------
def artist_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Ada Rivers",
        "email": "ada.rivers@example.org",
        "residency_start_date": "2023-01-10",
        "residency_county": "Lakeshore",
        "region": "NORTH",
        "is_enrolled_student": False,
        "tin_status": "MISSING",
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def application_payload(
    cycle_id: str, discipline_category_id: str, artist_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "discipline_category_id": discipline_category_id,
        "artist_id": artist_id,
        "artist_statement": (
            "I write short fiction about lake towns and the people who leave them."
        ),
        "career_narrative": (
            "Fifteen years of small-press publication, two chapbooks and a "
            "residency at the county library."
        ),
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# WorkSample
# ---------------------------------------------------------------------------
def work_sample_payload(application_id: str, ordinal: int = 1, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "medium": "MANUSCRIPT_PAGES",
        "ordinal": ordinal,
        "page_count": 12,
        "contains_identifying_metadata": False,
    }
    payload.update(overrides)
    return _drop_none(payload)


def audio_sample_payload(application_id: str, ordinal: int = 1, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "medium": "AUDIO",
        "ordinal": ordinal,
        "duration_seconds": 300,
        "contains_identifying_metadata": False,
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Panel and Panelist
# ---------------------------------------------------------------------------
def panel_payload(cycle_id: str, discipline_category_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "discipline_category_id": discipline_category_id,
        "required_seats": 5,
        "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
        "deliberation_window_start": "2026-11-01T00:00:00Z",
        "deliberation_window_end": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return _drop_none(payload)


def panelist_payload(
    panel_id: str,
    full_name: str = "Iris Vance",
    region: str = "NORTH",
    expertise_codes: Optional[List[str]] = None,
    is_chair: bool = False,
    person_email: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "panel_id": panel_id,
        "person_email": person_email or unique_email("reader"),
        "full_name": full_name,
        "region": region,
        "expertise_codes": expertise_codes or ["LITERARY_ARTS"],
        "is_chair": is_chair,
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# ConflictDeclaration
# ---------------------------------------------------------------------------
def conflict_payload(
    panelist_id: str,
    application_id: str,
    relationship_type: str = "SAME_INSTITUTION",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "panelist_id": panelist_id,
        "application_id": application_id,
        "relationship_type": relationship_type,
        "disclosure_note": (
            "The applicant and I both hold appointments at the lakeshore arts centre."
        ),
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
def review_payload(
    application_id: str,
    panelist_id: str,
    artistic_excellence: int = 9,
    work_sample_quality: int = 8,
    career_impact: int = 7,
    public_value: int = 6,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "panelist_id": panelist_id,
        "artistic_excellence": artistic_excellence,
        "work_sample_quality": work_sample_quality,
        "career_impact": career_impact,
        "public_value": public_value,
        "comments": "Assured voice, uneven middle section.",
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Award
# ---------------------------------------------------------------------------
def accept_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
        "tax_certification_signed": True,
    }
    payload.update(overrides)
    return _drop_none(payload)


def board_action_payload(
    action: str, expected_cycle_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# FinalReport
# ---------------------------------------------------------------------------
def final_report_payload(award_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "award_id": award_id,
        "narrative": (
            "The fellowship funded a year of lake-town interviews and a "
            "finished collection."
        ),
        "public_value_statement": (
            "Six free public readings in three counties, all recorded for the "
            "state archive."
        ),
        "audience_reached_count": 420,
        "expenditure_summary": (
            "Travel 180000, transcription 240000, materials 60000, living costs 1020000."
        ),
    }
    payload.update(overrides)
    return _drop_none(payload)


def final_report_resubmit_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "narrative": (
            "Revised narrative with the requested expenditure detail restated in full."
        ),
        "public_value_statement": (
            "Six free public readings plus two school workshops added after the review."
        ),
        "audience_reached_count": 465,
        "expenditure_summary": (
            "Travel 180000, transcription 240000, materials 60000, living costs 1020000, "
            "workshop fees 0."
        ),
    }
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Appeal
# ---------------------------------------------------------------------------
def appeal_payload(
    application_id: str, grounds_code: str = "PANEL_COMPOSITION_DEFECT", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "grounds_code": grounds_code,
        "statement": (
            "The panel that scored my application did not carry the regional "
            "coverage the discipline requires."
        ),
    }
    payload.update(overrides)
    return _drop_none(payload)
