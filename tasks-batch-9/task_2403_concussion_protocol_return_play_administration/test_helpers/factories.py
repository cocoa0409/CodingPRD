"""
Request-payload factories.

Each builder returns a valid body for one write endpoint, with keyword overrides
so a test can vary exactly the one field it is exercising.  Passing
``field=None`` for an optional key omits it; use ``OMIT`` to drop a normally
required key when probing schema validation.
"""

from typing import Any, Dict, List, Optional

# Sentinel meaning "leave this key out of the body entirely".
OMIT = object()


def _build(pairs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in pairs.items() if v is not OMIT}


# ─── Clubs ───────────────────────────────────────────────────────────────────

def club_payload(
    name: str = "Harbor City Kraken",
    market_code: str = "HCK",
    exemption_slots_total: Any = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "name": name,
            "market_code": market_code,
            "exemption_slots_total": exemption_slots_total,
        }
    )
    payload.update(overrides)
    return payload


# ─── Clinicians ──────────────────────────────────────────────────────────────

def clinician_payload(
    full_name: str = "Dr Vance",
    affiliation: str = "CLUB_AFFILIATED",
    license_number: str = "LIC-1001",
    credential_expires_at: str = "2027-12-31T00:00:00Z",
    club_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "full_name": full_name,
            "affiliation": affiliation,
            "license_number": license_number,
            "credential_expires_at": credential_expires_at,
            "club_id": club_id,
        }
    )
    payload.update(overrides)
    return payload


def club_physician_payload(
    club_id: str,
    full_name: str = "Dr Vance",
    license_number: str = "LIC-1001",
    credential_expires_at: str = "2027-12-31T00:00:00Z",
) -> Dict[str, Any]:
    return clinician_payload(
        full_name=full_name,
        affiliation="CLUB_AFFILIATED",
        license_number=license_number,
        credential_expires_at=credential_expires_at,
        club_id=club_id,
    )


def observer_payload(
    full_name: str = "Dr Osei",
    license_number: str = "LIC-2001",
    credential_expires_at: str = "2027-12-31T00:00:00Z",
) -> Dict[str, Any]:
    return clinician_payload(
        full_name=full_name,
        affiliation="UNAFFILIATED_OBSERVER",
        license_number=license_number,
        credential_expires_at=credential_expires_at,
    )


def consultant_payload(
    full_name: str = "Dr Iyer",
    license_number: str = "LIC-3001",
    credential_expires_at: str = "2027-12-31T00:00:00Z",
) -> Dict[str, Any]:
    return clinician_payload(
        full_name=full_name,
        affiliation="INDEPENDENT_CONSULTANT",
        license_number=license_number,
        credential_expires_at=credential_expires_at,
    )


def suspend_payload(reason: str = "license board inquiry opened") -> Dict[str, Any]:
    return {"reason": reason}


# ─── Players ─────────────────────────────────────────────────────────────────

def player_payload(
    club_id: str,
    full_name: str = "K Mbeki",
    jersey_number: Any = 24,
    position: Any = "WR",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "club_id": club_id,
            "full_name": full_name,
            "jersey_number": jersey_number,
            "position": position,
        }
    )
    payload.update(overrides)
    return payload


# ─── Games ───────────────────────────────────────────────────────────────────

def game_payload(
    home_club_id: str,
    away_club_id: str,
    season_year: Any = 2026,
    week_index: Any = 1,
    kickoff_at: str = "2026-09-13T17:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "season_year": season_year,
            "week_index": week_index,
            "home_club_id": home_club_id,
            "away_club_id": away_club_id,
            "kickoff_at": kickoff_at,
        }
    )
    payload.update(overrides)
    return payload


def advance_status_payload(to_status: str = "IN_PROGRESS") -> Dict[str, Any]:
    return {"to_status": to_status}


# ─── Baseline tests ──────────────────────────────────────────────────────────

def baseline_payload(
    player_id: str,
    expected_player_version: Any,
    season_year: Any = 2026,
    composite_score: Any = 88,
    reaction_time_ms: Any = 520,
    symptom_score: Any = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "player_id": player_id,
            "season_year": season_year,
            "composite_score": composite_score,
            "reaction_time_ms": reaction_time_ms,
            "symptom_score": symptom_score,
            "expected_player_version": expected_player_version,
        }
    )
    payload.update(overrides)
    return payload


def invalidate_payload(reason: str = "administration error in the test protocol") -> Dict[str, Any]:
    return {"reason": reason}


# ─── Sideline evaluations ────────────────────────────────────────────────────

def evaluation_payload(
    player_id: str,
    game_id: str,
    trigger_source: Any = "UNAFFILIATED_OBSERVER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "player_id": player_id,
            "game_id": game_id,
            "trigger_source": trigger_source,
        }
    )
    payload.update(overrides)
    return payload


def screen_payload(
    no_go_signs: Optional[List[str]] = None,
    symptom_score: Any = 9,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "no_go_signs": ["ATAXIA"] if no_go_signs is None else no_go_signs,
            "symptom_score": symptom_score,
        }
    )
    payload.update(overrides)
    return payload


def locker_room_exam_payload(inc_clinician_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = _build({"inc_clinician_id": inc_clinician_id})
    payload.update(overrides)
    return payload


def diagnose_payload(
    symptom_score: Any = 9,
    composite_score: Any = 70,
    documentation_note: Any = "no-go sign ataxia, removed from play",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "symptom_score": symptom_score,
            "composite_score": composite_score,
            "documentation_note": documentation_note,
        }
    )
    payload.update(overrides)
    return payload


def conclude_payload(
    outcome: Any = "NO_CONCUSSION",
    documentation_note: Any = "full neurological examination unremarkable",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build({"outcome": outcome, "documentation_note": documentation_note})
    payload.update(overrides)
    return payload


def clear_to_return_payload(
    documentation_note: Any = "screen clean, returned to the field",
) -> Dict[str, Any]:
    return _build({"documentation_note": documentation_note})


# ─── Return steps ────────────────────────────────────────────────────────────

def return_step_payload(stage_index: Any = 1, **overrides: Any) -> Dict[str, Any]:
    payload = _build({"stage_index": stage_index})
    payload.update(overrides)
    return payload


def evaluate_step_payload(
    outcome: Any = "PASS", symptom_score: Any = 0, **overrides: Any
) -> Dict[str, Any]:
    payload = _build({"outcome": outcome, "symptom_score": symptom_score})
    payload.update(overrides)
    return payload


# ─── Consultant clearances ───────────────────────────────────────────────────

def clearance_request_payload(
    inc_clinician_id: str, expected_case_version: Any, **overrides: Any
) -> Dict[str, Any]:
    payload = _build(
        {
            "inc_clinician_id": inc_clinician_id,
            "expected_case_version": expected_case_version,
        }
    )
    payload.update(overrides)
    return payload


def clearance_decision_payload(
    decision: Any = "APPROVED",
    decision_notes: Any = "asymptomatic, neurocognitive scores back to baseline",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build({"decision": decision, "decision_notes": decision_notes})
    payload.update(overrides)
    return payload


# ─── Concussion case actions ─────────────────────────────────────────────────

def symptom_check_payload(symptom_score: Any = 5, **overrides: Any) -> Dict[str, Any]:
    payload = _build({"symptom_score": symptom_score})
    payload.update(overrides)
    return payload


def return_to_contact_payload(
    documentation_note: Any = "full clearance, unrestricted contact",
) -> Dict[str, Any]:
    return _build({"documentation_note": documentation_note})


# ─── Protocol audits ─────────────────────────────────────────────────────────

def audit_payload(
    club_id: str, case_id: Any = OMIT, sideline_evaluation_id: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    payload = _build(
        {
            "club_id": club_id,
            "case_id": case_id,
            "sideline_evaluation_id": sideline_evaluation_id,
        }
    )
    payload.update(overrides)
    return payload


def findings_payload(
    violation_codes: Any = None, exposure_days: Any = 0, **overrides: Any
) -> Dict[str, Any]:
    payload = _build(
        {
            "violation_codes": (
                ["MISSED_MANDATORY_REMOVAL"] if violation_codes is None else violation_codes
            ),
            "exposure_days": exposure_days,
        }
    )
    payload.update(overrides)
    return payload


def audit_response_payload(
    response_note: Any = "the filing delay was caused by a league portal outage",
) -> Dict[str, Any]:
    return _build({"response_note": response_note})


def audit_close_payload(
    disposition: Any = "UPHELD", closing_note: Any = "violation upheld on review", **overrides: Any
) -> Dict[str, Any]:
    payload = _build({"disposition": disposition, "closing_note": closing_note})
    payload.update(overrides)
    return payload


# ─── Injury report entries ───────────────────────────────────────────────────

def injury_report_payload(
    game_id: str,
    player_id: str,
    practice_participation: Any = "DNP",
    designation: Any = "OUT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _build(
        {
            "game_id": game_id,
            "player_id": player_id,
            "practice_participation": practice_participation,
            "designation": designation,
        }
    )
    payload.update(overrides)
    return payload


def injury_report_amendment_payload(
    practice_participation: Any = "LIMITED", designation: Any = "QUESTIONABLE", **overrides: Any
) -> Dict[str, Any]:
    payload = _build(
        {"practice_participation": practice_participation, "designation": designation}
    )
    payload.update(overrides)
    return payload
