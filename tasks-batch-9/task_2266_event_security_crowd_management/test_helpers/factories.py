"""Payload factories.

Each factory returns a well-formed create/update body containing only the
client-supplied fields declared for that endpoint. Derived and system-managed
fields are never included. Keyword overrides let a test perturb exactly one
field while keeping the rest valid.
"""

from typing import Any, Dict, Optional

from .types import (
    CrowdProfile,
    EmploymentType,
    EventType,
    IncidentCategory,
    LaneType,
    PostType,
    ProtestLikelihood,
    Severity,
    ThreatLevel,
    ZoneType,
)

# ─── Reference instants used across the fixtures ──────

PLANNING_CLOCK = "2026-09-01T00:00:00Z"
DOORS_OPEN_AT = "2026-09-12T17:00:00Z"
EVENT_START_AT = "2026-09-12T18:30:00Z"
EVENT_END_AT = "2026-09-12T22:30:00Z"
POST_WINDOW_START = "2026-09-12T15:00:00Z"
POST_WINDOW_END = "2026-09-12T22:30:00Z"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; the ``OMIT`` sentinel deletes the key entirely.

    The sentinel is honoured in ``base`` as well as in ``overrides``, so a factory
    whose declared parameter carries the same name as a payload key can still be
    told to drop that key (``post_assignment_payload(post_id, guard_id=OMIT)``).
    """
    payload = dict(base)
    for key, value in overrides.items():
        payload[key] = value
    return {key: value for key, value in payload.items() if value is not _OMIT}


class _Omit:
    """Sentinel meaning 'drop this key from the payload'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Venue ────────────────────────────────────────────


def venue_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Harbor Arena",
            "gross_capacity": 8000,
            "door_count": 1,
            "egress_capacity_per_minute": 500,
            "perimeter_length_m": 400,
            "alcohol_licensed": False,
            "prior_incident_rate": 0,
        },
        overrides,
    )


# ─── Venue zone ───────────────────────────────────────


def zone_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "zone_code": "ZF",
            "zone_type": ZoneType.FLOOR,
            "floor_area_sqm": 200,
            "posted_capacity": 300,
            "exit_units": 3,
            "post_slot_capacity": 12,
            "is_ingress_zone": False,
        },
        overrides,
    )


def floor_zone_payload(**overrides: Any) -> Dict[str, Any]:
    return zone_payload(**overrides)


def ingress_zone_payload(**overrides: Any) -> Dict[str, Any]:
    return zone_payload(
        **_merge(
            {
                "zone_code": "ZI",
                "zone_type": ZoneType.CONCOURSE,
                "floor_area_sqm": 100,
                "posted_capacity": 150,
                "exit_units": 2,
                "post_slot_capacity": 12,
                "is_ingress_zone": True,
            },
            overrides,
        )
    )


def exit_zone_payload(**overrides: Any) -> Dict[str, Any]:
    return zone_payload(
        **_merge(
            {
                "zone_code": "ZE",
                "zone_type": ZoneType.EXIT_CORRIDOR,
                "floor_area_sqm": 50,
                "posted_capacity": 80,
                "exit_units": 1,
                "post_slot_capacity": 6,
                "is_ingress_zone": False,
            },
            overrides,
        )
    )


# ─── Security event ───────────────────────────────────


def event_payload(venue_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "venue_id": venue_id,
            "event_name": "Autumn Gala",
            "event_type": EventType.CONCERT,
            "doors_open_at": DOORS_OPEN_AT,
            "event_start_at": EVENT_START_AT,
            "event_end_at": EVENT_END_AT,
            "expected_attendance": 200,
            "alcohol_served": False,
            "vip_present": False,
        },
        overrides,
    )


# ─── Risk assessment ──────────────────────────────────


def risk_assessment_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "threat_level_input": ThreatLevel.LOW,
            "protest_likelihood": ProtestLikelihood.NONE,
            "crowd_profile": CrowdProfile.SEATED,
            "ingress_door_count": 1,
            "layout_complexity_score": 1,
            "history_incident_rate": 0,
        },
        overrides,
    )


# ─── Staffing plan ────────────────────────────────────


def staffing_plan_payload(
    risk_assessment_id: str, expected_event_version: int, budget_cents: int = 500000, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "risk_assessment_id": risk_assessment_id,
            "budget_cents": budget_cents,
            "expected_event_version": expected_event_version,
        },
        overrides,
    )


# ─── Post ─────────────────────────────────────────────


def post_payload(zone_id: str, post_code: str, post_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "zone_id": zone_id,
            "post_code": post_code,
            "post_type": post_type,
            "required_guard_count": 1,
            "min_credential_level": 1,
            "window_start": POST_WINDOW_START,
            "window_end": POST_WINDOW_END,
        },
        overrides,
    )


def supervisor_post_payload(zone_id: str, post_code: str = "S1", **overrides: Any) -> Dict[str, Any]:
    return post_payload(
        zone_id,
        post_code,
        PostType.SUPERVISOR,
        **_merge({"required_guard_count": 1, "min_credential_level": 3}, overrides),
    )


# ─── Subcontractor ────────────────────────────────────


def subcontractor_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "company_name": "Vanguard Protective",
            "license_number": "SC-3001",
            "insurance_expires_on": "2027-06-30T00:00:00Z",
            "markup_pct": 0.18,
        },
        overrides,
    )


# ─── Guard ────────────────────────────────────────────


def guard_payload(license_number: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Gale One",
            "employment_type": EmploymentType.EMPLOYEE,
            "credential_level": 1,
            "license_number": license_number,
            "credential_expires_on": "2026-12-31T00:00:00Z",
            "base_hourly_rate_cents": 2200,
        },
        overrides,
    )


def subcontracted_guard_payload(
    license_number: str, subcontractor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return guard_payload(
        license_number,
        **_merge(
            {
                "full_name": "Vendor Hand",
                "employment_type": EmploymentType.SUBCONTRACTED,
                "subcontractor_id": subcontractor_id,
                "base_hourly_rate_cents": 2400,
            },
            overrides,
        ),
    )


# ─── Post assignment ──────────────────────────────────


def post_assignment_payload(post_id: str, guard_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "post_id": post_id,
            "guard_id": guard_id,
            "window_start": POST_WINDOW_START,
            "window_end": POST_WINDOW_END,
        },
        overrides,
    )


# ─── Screening lane ───────────────────────────────────


def screening_lane_payload(zone_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "zone_id": zone_id,
            "lane_type": LaneType.BAG_CHECK,
            "nominal_throughput_pph": 195,
            "operator_capacity": 1,
            "open_from": "2026-09-12T16:00:00Z",
            "open_to": "2026-09-12T19:00:00Z",
        },
        overrides,
    )


# ─── Density reading ──────────────────────────────────


def density_reading_payload(
    zone_id: str, observed_at: str, observed_occupancy: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "zone_id": zone_id,
            "observed_at": observed_at,
            "observed_occupancy": observed_occupancy,
        },
        overrides,
    )


# ─── Incident ─────────────────────────────────────────


def incident_payload(
    zone_id: str,
    category: str = IncidentCategory.MEDICAL,
    severity: str = Severity.MODERATE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "zone_id": zone_id,
            "category": category,
            "severity": severity,
            "description": "patron unwell near the barrier",
        },
        overrides,
    )


# ─── After-action review ──────────────────────────────


def after_action_review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "narrative": "doors held twice, one medical handoff, one no-show on the floor post",
            "corrective_action_count": 3,
        },
        overrides,
    )


# ─── Action bodies ────────────────────────────────────


def action(name: str, **extra: Any) -> Dict[str, Any]:
    """Body for any of the action / lifecycle / decision endpoints."""
    payload: Dict[str, Any] = {"action": name}
    payload.update({k: v for k, v in extra.items() if v is not _OMIT})
    return payload


def brief_action(radio_channel: str = "CH1", training_module_code: str = "TM-GALA-01") -> Dict[str, Any]:
    return action("BRIEF", radio_channel=radio_channel, training_module_code=training_module_code)


def cancel_action(reason: Optional[str] = "roster churn") -> Dict[str, Any]:
    return action("CANCEL", cancellation_reason=reason)
