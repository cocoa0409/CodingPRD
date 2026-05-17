"""Lookup helpers — fetch entities by id and raise ERR_NOT_FOUND if missing."""
from __future__ import annotations

from typing import Any

from ..errors import err_not_found
from ..store import store


def get_trial(trial_id: str) -> dict[str, Any]:
    t = store().trials.get(trial_id)
    if t is None:
        raise err_not_found(f"Trial '{trial_id}' not found")
    return t


def get_participant(participant_id: str) -> dict[str, Any]:
    p = store().participants.get(participant_id)
    if p is None:
        raise err_not_found(f"Participant '{participant_id}' not found")
    return p


def get_visit(visit_id: str) -> dict[str, Any]:
    v = store().visits.get(visit_id)
    if v is None:
        raise err_not_found(f"Visit '{visit_id}' not found")
    return v


def get_arm(arm_id: str) -> dict[str, Any]:
    a = store().arms.get(arm_id)
    if a is None:
        raise err_not_found(f"Arm '{arm_id}' not found")
    return a


def get_adverse_event(ae_id: str) -> dict[str, Any]:
    ae = store().adverse_events.get(ae_id)
    if ae is None:
        raise err_not_found(f"Adverse event '{ae_id}' not found")
    return ae


def arms_for_trial(trial_id: str) -> list[dict[str, Any]]:
    return [a for a in store().arms.values() if a["trial_id"] == trial_id]


def consent_versions_for_trial(trial_id: str) -> list[dict[str, Any]]:
    rows = [c for c in store().consent_versions.values() if c["trial_id"] == trial_id]
    rows.sort(key=lambda c: c["version"])
    return rows


def irb_reviews_for_trial(trial_id: str) -> list[dict[str, Any]]:
    rows = [r for r in store().irb_reviews.values() if r["trial_id"] == trial_id]
    rows.sort(key=lambda r: r["created_at"])
    return rows


def participants_for_trial(trial_id: str) -> list[dict[str, Any]]:
    return [p for p in store().participants.values() if p["trial_id"] == trial_id]


def visits_for_participant(participant_id: str) -> list[dict[str, Any]]:
    rows = [v for v in store().visits.values() if v["participant_id"] == participant_id]
    rows.sort(key=lambda v: v["created_at"])
    return rows


def adverse_events_for_participant(participant_id: str) -> list[dict[str, Any]]:
    rows = [ae for ae in store().adverse_events.values() if ae["participant_id"] == participant_id]
    rows.sort(key=lambda ae: ae["created_at"])
    return rows


def payments_for_participant(participant_id: str) -> list[dict[str, Any]]:
    rows = [p for p in store().payments.values() if p["participant_id"] == participant_id]
    rows.sort(key=lambda p: p["created_at"])
    return rows


def open_ae_count_for(participant_id: str) -> int:
    """Recompute open_ae_count: count of AE rows in any non-terminal status.

    Per scaffold §1.2 AE state machine, only RESOLVED is terminal. The three other
    statuses — OPEN, UNDER_REVIEW, and ESCALATED_HOLD — all count as open against
    the visit-complete and participant-complete gates.
    """
    return sum(
        1
        for ae in store().adverse_events.values()
        if ae["participant_id"] == participant_id
        and ae["status"] in {"OPEN", "UNDER_REVIEW", "ESCALATED_HOLD"}
    )
