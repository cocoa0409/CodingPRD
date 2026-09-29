"""Request-payload builders.

Every builder returns a valid payload for its endpoint using the required
fields the PRD declares, and accepts `**overrides` so a test can perturb one
field at a time. Optional fields are omitted unless a caller supplies them, so
that server-side defaults stay observable.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of `None` removes the key entirely."""
    result = dict(payload)
    for key, value in overrides.items():
        if value is None and key in result:
            del result[key]
        else:
            result[key] = value
    return result


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

def clock_payload(current_utc: str = C.FIXTURE_CLOCK, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# --------------------------------------------------------------------------
# Season (PRD §3.1)
# --------------------------------------------------------------------------

def season_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Youth Orchestra Season",
            "year_label": "2026-27",
            "audition_window_start": C.SEASON_AUDITION_WINDOW_START,
            "audition_window_end": C.SEASON_AUDITION_WINDOW_END,
            "tuition_base_cents": C.SEASON_TUITION_BASE_CENTS,
            "tuition_due_at": C.SEASON_TUITION_DUE_AT,
            "aid_budget_cents": C.SEASON_AID_BUDGET_CENTS,
        },
        overrides,
    )


def advance_status_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


def aid_award_run_payload(expected_season_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_season_version": expected_season_version}, overrides)


# --------------------------------------------------------------------------
# Ensemble (PRD §3.1)
# --------------------------------------------------------------------------

def ensemble_payload(season_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "name": "Youth Symphony",
            "tier": "PHILHARMONIC",
            "min_total_size": 1,
            "max_total_size": 10,
            "rehearsal_weekday": "MON",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# SectionQuota (PRD §3.1)
# --------------------------------------------------------------------------

def section_quota_payload(ensemble_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "ensemble_id": ensemble_id,
            "instrument": "CELLO",
            "min_count": 1,
            "target_count": 1,
            "max_count": 4,
        },
        overrides,
    )


def rotate_chairs_payload(expected_ensemble_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_ensemble_version": expected_ensemble_version}, overrides)


# --------------------------------------------------------------------------
# Member (PRD §3.2)
# --------------------------------------------------------------------------

def member_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Avery Lin",
            "primary_instrument": "CELLO",
            "grade_level": 10,
            "graduation_year": 2028,
            "household_income_band": "BAND_C",
        },
        overrides,
    )


def member_status_transition_payload(
    dimension: str, to_status: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"dimension": dimension, "to_status": to_status}, overrides)


# --------------------------------------------------------------------------
# Panelist (PRD §3.2)
# --------------------------------------------------------------------------

def panelist_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "display_name": "Dr. Rowan Vale",
            "instrument_expertise": "CELLO",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# AuditionSlot (PRD §3.3)
# --------------------------------------------------------------------------

def audition_slot_payload(
    season_id: str, panelist_ids: List[str], **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "room_code": "ROOM-A",
            "start_at": C.SLOT_START_AT,
            "end_at": C.SLOT_END_AT,
            "panelist_ids": list(panelist_ids),
            "instrument_focus": "CELLO",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Audition (PRD §3.4)
# --------------------------------------------------------------------------

def audition_payload(member_id: str, season_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "member_id": member_id,
            "season_id": season_id,
            "declared_program": "Elgar Cello Concerto, first movement",
            "excerpt_ids": ["EX-1"],
        },
        overrides,
    )


def schedule_payload(slot_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"slot_id": slot_id}, overrides)


def panel_score_payload(
    panelist_id: str,
    tone_score: int = 20,
    rhythm_score: int = 20,
    intonation_score: int = 20,
    sight_reading_score: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "panelist_id": panelist_id,
            "tone_score": tone_score,
            "rhythm_score": rhythm_score,
            "intonation_score": intonation_score,
            "sight_reading_score": sight_reading_score,
        },
        overrides,
    )


def uniform_panel_score_payload(panelist_id: str, value: int, **overrides: Any) -> Dict[str, Any]:
    """All four rubric integers equal, so `weighted_total` is exactly 4 x value."""
    return panel_score_payload(
        panelist_id,
        tone_score=value,
        rhythm_score=value,
        intonation_score=value,
        sight_reading_score=value,
        **overrides,
    )


# --------------------------------------------------------------------------
# Placement (PRD §3.5)
# --------------------------------------------------------------------------

def placement_payload(
    audition_id: str,
    ensemble_id: str,
    expected_ensemble_version: int,
    offer_kind: str = "OFFER",
    offer_expires_at: Optional[str] = C.OFFER_EXPIRES_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audition_id": audition_id,
        "ensemble_id": ensemble_id,
        "offer_kind": offer_kind,
        "expected_ensemble_version": expected_ensemble_version,
    }
    if offer_kind == "OFFER" and offer_expires_at is not None:
        payload["offer_expires_at"] = offer_expires_at
    return _merge(payload, overrides)


def accept_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


def aid_request_payload(aid_requested_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"aid_requested_cents": aid_requested_cents}, overrides)


# --------------------------------------------------------------------------
# EnsembleEvent (PRD §3.8)
# --------------------------------------------------------------------------

def ensemble_event_payload(
    ensemble_id: str,
    kind: str = "REHEARSAL",
    start_at: str = "2026-09-07T18:00:00Z",
    end_at: str = "2026-09-07T20:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "ensemble_id": ensemble_id,
            "kind": kind,
            "start_at": start_at,
            "end_at": end_at,
            "venue_code": "HALL-1",
        },
        overrides,
    )


def programming_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# --------------------------------------------------------------------------
# EventParticipation (PRD §3.8)
# --------------------------------------------------------------------------

def participation_payload(event_id: str, member_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"event_id": event_id, "member_id": member_id}, overrides)


def attendance_payload(attendance_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"attendance_status": attendance_status}, overrides)


def excuse_request_payload(
    excuse_reason_code: str = "ILLNESS", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"excuse_reason_code": excuse_reason_code}, overrides)


def excuse_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def eligibility_review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def tour_requirements_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)
