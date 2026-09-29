"""Request-payload builders.

Every builder emits only fields the API declares for that endpoint, because
unknown fields are rejected outright. Callers override any field by keyword and
may drop a field entirely by passing ``None`` for an optional one.
"""

import itertools

_counter = itertools.count(1)


def unique_suffix():
    """A short, monotonically increasing discriminator for names and rooms."""
    return next(_counter)


def _compact(payload, overrides):
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


# ---------------------------------------------------------------------------
# Census and clinical record
# ---------------------------------------------------------------------------
def resident_payload(
    full_name=None, room_number=None, admission_date="2026-07-01", status=None, **extra
):
    n = unique_suffix()
    return _compact(
        {
            "full_name": full_name or f"Resident {n}",
            "room_number": room_number or f"R{n:03d}A",
            "admission_date": admission_date,
            "status": status,
        },
        extra,
    )


def assessment_payload(
    cognitive_level="INTACT",
    functional_mobility="INDEPENDENT",
    interest_domains=None,
    preferred_group_size="SMALL",
    effective_date="2026-07-15",
    adaptive_equipment_needs=None,
    **extra,
):
    return _compact(
        {
            "cognitive_level": cognitive_level,
            "functional_mobility": functional_mobility,
            "interest_domains": interest_domains or ["SOCIAL"],
            "preferred_group_size": preferred_group_size,
            "effective_date": effective_date,
            "adaptive_equipment_needs": adaptive_equipment_needs,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Catalogue, rooms and fleet
# ---------------------------------------------------------------------------
def program_payload(
    name=None,
    domain="SOCIAL",
    staffing_ratio_denominator=4,
    max_group_size=10,
    max_supervision_tier="TIER_3",
    required_adaptive_equipment=None,
    volunteer_eligible=None,
    required_screening_level=None,
    **extra,
):
    return _compact(
        {
            "name": name or f"Program {unique_suffix()}",
            "domain": domain,
            "staffing_ratio_denominator": staffing_ratio_denominator,
            "max_group_size": max_group_size,
            "max_supervision_tier": max_supervision_tier,
            "required_adaptive_equipment": required_adaptive_equipment,
            "volunteer_eligible": volunteer_eligible,
            "required_screening_level": required_screening_level,
        },
        extra,
    )


def room_payload(
    name=None, capacity=10, buffer_minutes=0, equipment_available=None, **extra
):
    return _compact(
        {
            "name": name or f"Room {unique_suffix()}",
            "capacity": capacity,
            "buffer_minutes": buffer_minutes,
            "equipment_available": equipment_available,
        },
        extra,
    )


def vehicle_payload(
    label=None,
    ambulatory_seats=8,
    wheelchair_stations=2,
    turnaround_minutes=30,
    status=None,
    **extra,
):
    return _compact(
        {
            "label": label or f"Van {unique_suffix()}",
            "ambulatory_seats": ambulatory_seats,
            "wheelchair_stations": wheelchair_stations,
            "turnaround_minutes": turnaround_minutes,
            "status": status,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
def domain_targets(social=0, cognitive=0, physical=0, spiritual=0, creative=0):
    """A complete five-key target map, which is the only shape the API accepts."""
    return {
        "SOCIAL": social,
        "COGNITIVE": cognitive,
        "PHYSICAL": physical,
        "SPIRITUAL": spiritual,
        "CREATIVE": creative,
    }


def plan_payload(
    resident_id,
    source_assessment_id,
    expected_resident_version,
    cycle_start_at="2026-08-01T00:00:00Z",
    targets=None,
    **extra,
):
    return _compact(
        {
            "resident_id": resident_id,
            "source_assessment_id": source_assessment_id,
            "cycle_start_at": cycle_start_at,
            "domain_frequency_targets": targets or domain_targets(social=1),
            "expected_resident_version": expected_resident_version,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Calendar and documentation
# ---------------------------------------------------------------------------
def session_payload(
    program_id,
    room_id,
    starts_at="2026-08-03T09:00:00Z",
    ends_at="2026-08-03T10:00:00Z",
    assigned_staff_count=2,
    **extra,
):
    return _compact(
        {
            "program_id": program_id,
            "room_id": room_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "assigned_staff_count": assigned_staff_count,
        },
        extra,
    )


def enrollment_payload(resident_id, gate_override_reason=None, **extra):
    return _compact(
        {"resident_id": resident_id, "gate_override_reason": gate_override_reason}, extra
    )


def attendance_payload(engagement_level="ACTIVE", adaptive_equipment_used=None, **extra):
    return _compact(
        {
            "outcome": "ATTENDED",
            "engagement_level": engagement_level,
            "adaptive_equipment_used": adaptive_equipment_used,
        },
        extra,
    )


def refusal_payload(refusal_reason="FATIGUE", **extra):
    return _compact({"outcome": "REFUSED", "refusal_reason": refusal_reason}, extra)


def absence_payload(**extra):
    return _compact({"outcome": "ABSENT"}, extra)


# ---------------------------------------------------------------------------
# Volunteers
# ---------------------------------------------------------------------------
def volunteer_payload(full_name=None, volunteer_type="ADULT_COMMUNITY", **extra):
    return _compact(
        {
            "full_name": full_name or f"Volunteer {unique_suffix()}",
            "volunteer_type": volunteer_type,
        },
        extra,
    )


def assignment_payload(volunteer_id, session_id, role_type="GROUP_ASSISTANT", **extra):
    return _compact(
        {
            "volunteer_id": volunteer_id,
            "session_id": session_id,
            "role_type": role_type,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Outings
# ---------------------------------------------------------------------------
def outing_payload(
    program_id,
    vehicle_id,
    destination=None,
    departure_at="2026-08-20T09:00:00Z",
    return_at="2026-08-20T12:00:00Z",
    escort_count=1,
    **extra,
):
    return _compact(
        {
            "program_id": program_id,
            "vehicle_id": vehicle_id,
            "destination": destination or f"Destination {unique_suffix()}",
            "departure_at": departure_at,
            "return_at": return_at,
            "escort_count": escort_count,
        },
        extra,
    )


def consent_payload(
    resident_id,
    responsible_party_name=None,
    responsible_party_relation="GUARDIAN",
    expires_on=None,
    **extra,
):
    return _compact(
        {
            "resident_id": resident_id,
            "responsible_party_name": responsible_party_name
            or f"Family {unique_suffix()}",
            "responsible_party_relation": responsible_party_relation,
            "expires_on": expires_on,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Council and survey
# ---------------------------------------------------------------------------
def council_request_payload(
    resident_id,
    requested_domain="PHYSICAL",
    requested_program_id=None,
    vote_count=6,
    note=None,
    **extra,
):
    return _compact(
        {
            "resident_id": resident_id,
            "requested_domain": requested_domain,
            "requested_program_id": requested_program_id,
            "vote_count": vote_count,
            "note": note,
        },
        extra,
    )


def packet_payload(window_start="2026-08-01", window_end="2026-08-01", **extra):
    return _compact({"window_start": window_start, "window_end": window_end}, extra)
