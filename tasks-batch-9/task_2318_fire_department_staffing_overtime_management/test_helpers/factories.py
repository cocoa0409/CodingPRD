"""Request payload factories.

Each factory returns a valid minimal payload for one write endpoint and lets a
caller override any field with a keyword argument. Fields the PRD marks as
server-derived are never supplied by default.
"""

from typing import Any, Dict, List, Optional

from .constants import SHIFT_DATE_PLATOON_C

_STATION_SEQ = {"n": 0}
_UNIT_SEQ = {"n": 0}
_MEMBER_SEQ = {"n": 0}


def _next(counter: Dict[str, int]) -> int:
    counter["n"] += 1
    return counter["n"]


def station_payload(**overrides) -> Dict[str, Any]:
    """A station with a one-body staffing floor and a 90,000-dollar fiscal budget."""
    n = _next(_STATION_SEQ)
    payload: Dict[str, Any] = {
        "name": f"Station {40 + n}",
        "battalion_code": "C1",
        "minimum_staffing_floor": 1,
        "fiscal_ot_budget_cents": 9_000_000,
        "fiscal_period_start_date": "2026-08-01",
        "fiscal_period_end_date": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def apparatus_payload(station_id: str, **overrides) -> Dict[str, Any]:
    """A single-seat engine company with no certification requirement."""
    n = _next(_UNIT_SEQ)
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "unit_designation": f"ENGINE-{n}",
        "apparatus_type": "ENGINE",
        "minimum_crew_size": 1,
        "required_certifications": [],
        "closure_priority": 10,
    }
    payload.update(overrides)
    return payload


def firefighter_payload(station_id: str, **overrides) -> Dict[str, Any]:
    """An active platoon C member with no certifications."""
    n = _next(_MEMBER_SEQ)
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "full_name": f"Member {n:03d}",
        "rank": "FIREFIGHTER",
        "platoon": "C",
        "seniority_rank": n,
        "kelly_day_cycle_position": 1,
        "certifications": [],
        "hourly_rate_cents": 4000,
    }
    payload.update(overrides)
    return payload


def hiring_roster_payload(station_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "roster_type": "VOLUNTARY_OT",
        "certification_scope": "NONE",
    }
    payload.update(overrides)
    return payload


def duty_shift_payload(station_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "shift_date": SHIFT_DATE_PLATOON_C,
        "platoon": "C",
    }
    payload.update(overrides)
    return payload


def shift_assignment_payload(
    duty_shift_id: str,
    firefighter_id: str,
    apparatus_id: str,
    expected_duty_shift_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "duty_shift_id": duty_shift_id,
        "firefighter_id": firefighter_id,
        "apparatus_id": apparatus_id,
        "assignment_type": "REGULAR",
        "seat_certification": "NONE",
        "scheduled_hours": 24,
        "expected_duty_shift_version": expected_duty_shift_version,
    }
    payload.update(overrides)
    return payload


def leave_request_payload(
    firefighter_id: str, duty_shift_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "firefighter_id": firefighter_id,
        "duty_shift_id": duty_shift_id,
        "leave_type": "VACATION",
        "requested_hours": 24,
    }
    payload.update(overrides)
    return payload


def trade_request_payload(
    requesting_firefighter_id: str,
    counterparty_firefighter_id: str,
    duty_shift_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requesting_firefighter_id": requesting_firefighter_id,
        "counterparty_firefighter_id": counterparty_firefighter_id,
        "duty_shift_id": duty_shift_id,
    }
    payload.update(overrides)
    return payload


def offer_payload(hiring_mode: str = "VOLUNTARY", offer_hours: int = 24) -> Dict[str, Any]:
    return {"hiring_mode": hiring_mode, "offer_hours": offer_hours}


def availability_payload(
    expected_firefighter_version: int,
    effective_date: str = "2026-08-05",
    employment_status: Optional[str] = None,
    roster_standing: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_firefighter_version": expected_firefighter_version,
        "effective_date": effective_date,
    }
    if employment_status is not None:
        payload["employment_status"] = employment_status
    if roster_standing is not None:
        payload["roster_standing"] = roster_standing
    return payload


def hour_adjustment_payload(
    adjustment_hours: int,
    adjustment_basis: str = "SCHEDULED",
    reason: str = "carry-in hours from the prior 7(k) period",
) -> Dict[str, Any]:
    return {
        "adjustment_hours": adjustment_hours,
        "adjustment_basis": adjustment_basis,
        "reason": reason,
    }


def closure_payload(
    expected_duty_shift_version: int,
    justification: str = "battalion cannot fill the remaining seats for this tour",
) -> Dict[str, Any]:
    return {
        "expected_duty_shift_version": expected_duty_shift_version,
        "justification": justification,
    }


def certifications(*values: str) -> List[str]:
    return list(values)
