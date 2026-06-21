"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Optional


# --- Chapter (PRD §3.1) ------------------------------------------------------
def create_chapter_payload(
    name: str = "Test Chapter",
    greek_type: str = "SORORITY",
    quota_total: int = 5,
    dues_per_member_cents: int = 10000,
    legacy_priority_slots: int = 0,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "greek_type": greek_type,
        "quota_total": quota_total,
        "dues_per_member_cents": dues_per_member_cents,
        "legacy_priority_slots": legacy_priority_slots,
    }
    payload.update(overrides)
    return payload


def update_chapter_payload(**overrides) -> dict:
    """For PUT /rush/chapters/{id}; all fields optional."""
    return dict(overrides)


# --- PNM (PRD §3.1) ----------------------------------------------------------
def register_pnm_payload(
    full_name: str = "Test PNM",
    gpa: float = 3.50,
    legacy_chapter_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload: dict = {
        "full_name": full_name,
        "gpa": gpa,
    }
    if legacy_chapter_id is not None:
        payload["legacy_chapter_id"] = legacy_chapter_id
    payload.update(overrides)
    return payload


# --- RecruitmentRound (PRD §3.1) ---------------------------------------------
def create_round_payload(
    cycle_label: str = "Fall 2026",
    bid_day_at: str = "2026-09-15T12:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "cycle_label": cycle_label,
        "bid_day_at": bid_day_at,
    }
    payload.update(overrides)
    return payload


# --- Party (PRD §3.2) --------------------------------------------------------
def create_party_payload(
    round_id: str,
    chapter_id: str,
    scheduled_start_utc: str = "2026-09-05T18:00:00Z",
    duration_minutes: int = 60,
    capacity: int = 10,
    **overrides,
) -> dict:
    payload = {
        "round_id": round_id,
        "chapter_id": chapter_id,
        "scheduled_start_utc": scheduled_start_utc,
        "duration_minutes": duration_minutes,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


# --- PartyInvitation (PRD §3.3) ----------------------------------------------
def create_invitation_payload(party_id: str, pnm_id: str, **overrides) -> dict:
    payload = {"party_id": party_id, "pnm_id": pnm_id}
    payload.update(overrides)
    return payload


# --- Preference (PRD §3.4) ---------------------------------------------------
def create_preference_payload(
    round_id: str,
    side: str,
    pnm_id: str,
    chapter_id: str,
    rank: int = 1,
    **overrides,
) -> dict:
    payload = {
        "round_id": round_id,
        "side": side,
        "pnm_id": pnm_id,
        "chapter_id": chapter_id,
        "rank": rank,
    }
    payload.update(overrides)
    return payload


# --- BidMatch (PRD §3.5) -----------------------------------------------------
def create_bid_match_payload(
    round_id: str,
    chapter_id: str,
    pnm_id: str,
    expected_chapter_version: int,
    **overrides,
) -> dict:
    payload = {
        "round_id": round_id,
        "chapter_id": chapter_id,
        "pnm_id": pnm_id,
        "expected_chapter_version": expected_chapter_version,
    }
    payload.update(overrides)
    return payload


def rescind_bid_match_payload(expected_chapter_version: int, **overrides) -> dict:
    payload = {"expected_chapter_version": expected_chapter_version}
    payload.update(overrides)
    return payload


# --- RiskIncident (PRD §3.8) -------------------------------------------------
def create_risk_incident_payload(
    chapter_id: str,
    severity_points: int = 5,
    reason: str = "test incident",
    party_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload: dict = {
        "chapter_id": chapter_id,
        "severity_points": severity_points,
        "reason": reason,
    }
    if party_id is not None:
        payload["party_id"] = party_id
    payload.update(overrides)
    return payload


# --- Clock (PRD §3.9) --------------------------------------------------------
def set_clock_payload(to_iso8601: str = "2026-09-01T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
