"""Payload factories — one per entity, input fields only.

Only fields the client supplies on creation are present. Server-minted and
computed fields (id, status, version, bed_capacity, amount_cents, etc.) are
never sent.
"""

DEFAULTS = {
    "BUILDING_NAME": "Test Hall",
    "ROOM_NUMBER": "101",
    "STUDENT_NAME": "Test Student",
    "TERM_LABEL": "FALL_2026",
}


def create_building_payload(**overrides) -> dict:
    """Input fields for POST /buildings (PRD §3.1).

    offers_break_housing and break_housing_capacity are optional with
    server-side defaults of false and 0; they are omitted unless overridden.
    """
    defaults = {
        "name": DEFAULTS["BUILDING_NAME"],
        "building_type": "TRADITIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    """Input fields for POST /buildings/{id}/rooms (PRD §3.1).

    nightly_break_rate_cents is optional (default 4500) and omitted unless set.
    """
    defaults = {
        "room_number": DEFAULTS["ROOM_NUMBER"],
        "room_type": "SINGLE",
        "gender_inclusivity": "ALL_GENDER",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    """Input fields for POST /students (PRD §3.2)."""
    defaults = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "class_year": "SENIOR",
        "gender_identity": "NONBINARY",
        "lottery_number": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    """Input fields for POST /housing-cycles (PRD §3.3)."""
    defaults = {
        "term_label": DEFAULTS["TERM_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(cycle_id, student_id, **overrides) -> dict:
    """Input fields for POST /applications (PRD §3.3).

    roommate_group_id is optional (default null) and omitted unless set.
    """
    defaults = {
        "cycle_id": cycle_id,
        "student_id": student_id,
        "preferred_building_type": "NO_PREFERENCE",
        "preferred_room_type": "NO_PREFERENCE",
    }
    defaults.update(overrides)
    return defaults


def create_roommate_group_payload(cycle_id, owner_student_id, **overrides) -> dict:
    """Input fields for POST /roommate-groups (PRD §3.5)."""
    defaults = {
        "cycle_id": cycle_id,
        "owner_student_id": owner_student_id,
        "target_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(student_id, **overrides) -> dict:
    """Input fields for POST /roommate-groups/{id}/memberships (PRD §3.5)."""
    defaults = {
        "student_id": student_id,
    }
    defaults.update(overrides)
    return defaults


def create_damage_charge_payload(assignment_id, **overrides) -> dict:
    """Input fields for POST /damage-charges (PRD §3.6)."""
    defaults = {
        "assignment_id": assignment_id,
        "category": "REPAIR",
        "assessed_cents": 10000,
        "split_basis": "SOLE",
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(room_id, reporter_student_id, **overrides) -> dict:
    """Input fields for POST /incident-reports (PRD §3.7)."""
    defaults = {
        "room_id": room_id,
        "reporter_student_id": reporter_student_id,
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_break_request_payload(assignment_id, check_in_date, check_out_date, **overrides) -> dict:
    """Input fields for POST /break-housing-requests (PRD §3.8)."""
    defaults = {
        "assignment_id": assignment_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    defaults.update(overrides)
    return defaults
