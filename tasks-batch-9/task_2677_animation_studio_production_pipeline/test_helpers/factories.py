"""Request-payload builders for the Studio Production Pipeline suite.

Every builder returns a plain dict holding only the field names the API
contract defines, with every money amount as an integer number of cents and
every ratio as a JSON number.  Callers override any field through keyword
arguments and delete a field by passing ``None`` for an optional one.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_START,
    COLOR_ACESCG,
    COLOR_REC709,
    DELIVERABLE_PROXY_MP4,
    FORMAT_FEATURE,
    PRIORITY_NORMAL,
    SESSION_DAILIES,
)

JsonDict = Dict[str, Any]

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def unique_suffix(width: int = 4) -> str:
    """A short unique token safe inside uppercase alphanumeric codes."""
    return str(_next()).rjust(width, "0")[-width:]


def _apply(payload: JsonDict, overrides: JsonDict) -> JsonDict:
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ----------------------------------------------------------------------
# Productions and gates
# ----------------------------------------------------------------------
def production_payload(**overrides: Any) -> JsonDict:
    """A minimal, valid production creation payload."""
    payload = {
        "title": "Northern Lights",
        "production_code": "AD" + unique_suffix(2),
        "format": FORMAT_FEATURE,
        "budget_cents": 100_000_000,
        "render_allowance_cents": 50_000_000,
        "master_color_space": COLOR_ACESCG,
    }
    return _apply(payload, overrides)


def advance_phase_payload(to_phase: str, **overrides: Any) -> JsonDict:
    return _apply({"to_phase": to_phase}, overrides)


def gate_submit_payload(package_url: str = "https://studio.example/gate/v1.pdf", **overrides: Any) -> JsonDict:
    return _apply({"package_url": package_url}, overrides)


def gate_decision_payload(decision: str, **overrides: Any) -> JsonDict:
    return _apply({"decision": decision}, overrides)


# ----------------------------------------------------------------------
# Assets
# ----------------------------------------------------------------------
def asset_payload(production_id: str, **overrides: Any) -> JsonDict:
    payload = {
        "production_id": production_id,
        "asset_code": "ASSET" + unique_suffix(3),
        "asset_type": "PROP",
        "base_complexity_points": 100.00,
    }
    return _apply(payload, overrides)


def advance_build_payload(to_build_status: str, **overrides: Any) -> JsonDict:
    return _apply({"to_build_status": to_build_status}, overrides)


def library_decision_payload(decision: str, **overrides: Any) -> JsonDict:
    return _apply({"decision": decision}, overrides)


def relink_payload(derived_from_asset_id: Optional[str], **overrides: Any) -> JsonDict:
    return _apply({"derived_from_asset_id": derived_from_asset_id}, overrides)


# ----------------------------------------------------------------------
# Shots and stage tasks
# ----------------------------------------------------------------------
def shot_payload(production_id: str, **overrides: Any) -> JsonDict:
    payload = {
        "production_id": production_id,
        "shot_code": "SH" + unique_suffix(4),
        "sequence_code": "010",
        "frame_count": 120,
        "budget_cents": 1_000_000,
        "planned_start_at": CLOCK_START,
        "planned_finish_at": "2026-08-31T00:00:00Z",
    }
    return _apply(payload, overrides)


def assign_payload(assigned_artist_user_id: str, **overrides: Any) -> JsonDict:
    return _apply({"assigned_artist_user_id": assigned_artist_user_id}, overrides)


def log_hours_payload(hours: float, **overrides: Any) -> JsonDict:
    return _apply({"hours": hours}, overrides)


def task_submit_payload(**overrides: Any) -> JsonDict:
    return _apply({}, overrides)


def task_decision_payload(decision: str, **overrides: Any) -> JsonDict:
    return _apply({"decision": decision}, overrides)


# ----------------------------------------------------------------------
# Screening rooms, sessions and notes
# ----------------------------------------------------------------------
def screening_room_payload(**overrides: Any) -> JsonDict:
    payload = {
        "name": "Theatre " + unique_suffix(2),
        "seat_capacity": 20,
        "room_color_space": COLOR_ACESCG,
    }
    return _apply(payload, overrides)


def review_session_payload(
    production_id: str, screening_room_id: str, **overrides: Any
) -> JsonDict:
    payload = {
        "production_id": production_id,
        "screening_room_id": screening_room_id,
        "session_type": SESSION_DAILIES,
        "window_start": "2026-08-01T10:00:00Z",
        "window_end": "2026-08-01T11:00:00Z",
        "attendee_count": 4,
    }
    return _apply(payload, overrides)


def director_note_payload(
    review_session_id: str, shot_stage_task_id: str, severity: str, **overrides: Any
) -> JsonDict:
    payload = {
        "review_session_id": review_session_id,
        "shot_stage_task_id": shot_stage_task_id,
        "severity": severity,
        "note_text": "Tighten the silhouette on the hero pass.",
    }
    return _apply(payload, overrides)


def note_resolution_payload(resolution: str, **overrides: Any) -> JsonDict:
    return _apply({"resolution": resolution}, overrides)


def session_cancel_payload(**overrides: Any) -> JsonDict:
    return _apply({}, overrides)


# ----------------------------------------------------------------------
# Render pools and jobs
# ----------------------------------------------------------------------
def render_pool_payload(**overrides: Any) -> JsonDict:
    payload = {
        "name": "Farm " + unique_suffix(2),
        "total_cores": 100,
        "cost_per_core_hour_cents": 175,
    }
    return _apply(payload, overrides)


def render_job_payload(
    render_pool_id: str,
    shot_stage_task_id: str,
    expected_render_pool_version: int,
    **overrides: Any,
) -> JsonDict:
    payload = {
        "render_pool_id": render_pool_id,
        "shot_stage_task_id": shot_stage_task_id,
        "priority": PRIORITY_NORMAL,
        "requested_cores": 3,
        "window_start": "2026-08-01T10:00:00Z",
        "window_end": "2026-08-01T16:00:00Z",
        "frame_count": 120,
        "seconds_per_frame": 50.00,
        "expected_render_pool_version": expected_render_pool_version,
    }
    return _apply(payload, overrides)


def render_settle_payload(
    outcome: str, actual_seconds_per_frame: float, frames_completed: int, **overrides: Any
) -> JsonDict:
    payload = {
        "outcome": outcome,
        "actual_seconds_per_frame": actual_seconds_per_frame,
        "frames_completed": frames_completed,
    }
    return _apply(payload, overrides)


# ----------------------------------------------------------------------
# Partners and packages
# ----------------------------------------------------------------------
def partner_payload(**overrides: Any) -> JsonDict:
    payload = {"legal_name": "Aurora Vendor " + unique_suffix(2)}
    return _apply(payload, overrides)


def partner_status_payload(status: str, **overrides: Any) -> JsonDict:
    return _apply({"status": status}, overrides)


def package_payload(
    production_id: str, partner_id: str, **overrides: Any
) -> JsonDict:
    payload = {
        "production_id": production_id,
        "partner_id": partner_id,
        "package_code": "PKG" + unique_suffix(3),
        "security_tier": "TIER1",
        "fee_cents": 500_000,
        "stage_task_ids": [],
    }
    return _apply(payload, overrides)


def package_deliver_payload(watermark_applied: bool = True, **overrides: Any) -> JsonDict:
    return _apply({"watermark_applied": watermark_applied}, overrides)


def package_qc_payload(decision: str, qc_score: int, **overrides: Any) -> JsonDict:
    # §2.8 enumerates the non-monetary fields that carry two decimal places and
    # `qc_score` is deliberately not among them, so the QC score is submitted as a
    # whole number between 0 and 100.
    return _apply({"decision": decision, "qc_score": qc_score}, overrides)


# ----------------------------------------------------------------------
# Deliverables
# ----------------------------------------------------------------------
def deliverable_payload(
    production_id: str, expected_production_version: int, **overrides: Any
) -> JsonDict:
    payload = {
        "production_id": production_id,
        "deliverable_type": DELIVERABLE_PROXY_MP4,
        "color_space": COLOR_ACESCG,
        "resolution": "3840x2160",
        "expected_production_version": expected_production_version,
    }
    return _apply(payload, overrides)


def deliverable_qc_payload(decision: str, **overrides: Any) -> JsonDict:
    return _apply({"decision": decision}, overrides)


# ----------------------------------------------------------------------
# Discovery helpers for cascade-created rows
# ----------------------------------------------------------------------
def find_by(rows: List[JsonDict], **match: Any) -> JsonDict:
    """Return the single row of a collection matching every named field."""
    hits = [row for row in rows if all(row.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"expected exactly one row matching {match}, found {len(hits)}"
    return hits[0]
