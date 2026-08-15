"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ROOM_NAME": "Parlor",
    "ROOM_FLOOR": 1,
    "ROOM_CAPACITY_MAX": 20,
    "ROOM_SAFETY_MAX_PARTY": 12,
    "ROOM_TIER": "STANDARD",
    "ROUTE_NAME": "Main Floor",
    "ROUTE_KIND": "STANDARD",
    "ROUTE_DURATION": 60,
    "ROUTE_BASE_PRICE": 1000,
    "SCRIPT_TEXT": "Welcome to the house",
    "SLOT_START": "2026-09-01T10:00:00Z",
    "DOCENT_NAME": "Dee Ocent",
    "DOCENT_EMAIL": "dee@x.org",
    "MEMBER_NAME": "Mel Member",
    "MEMBER_EMAIL": "mel@x.org",
    "MEMBER_NUMBER": "M-100",
    "MEMBER_RENEWS_ON": "2027-06-01",
    "VISITOR_NAME": "Ann",
    "INCIDENT_DESCRIPTION": "Water leak over the parquet",
}


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "floor": DEFAULTS["ROOM_FLOOR"],
        "capacity_max": DEFAULTS["ROOM_CAPACITY_MAX"],
        "safety_max_party": DEFAULTS["ROOM_SAFETY_MAX_PARTY"],
        "collection_tier": DEFAULTS["ROOM_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_tour_route_payload(room_ids, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROUTE_NAME"],
        "kind": DEFAULTS["ROUTE_KIND"],
        "room_ids": list(room_ids),
        "duration_minutes": DEFAULTS["ROUTE_DURATION"],
        "base_price_cents": DEFAULTS["ROUTE_BASE_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_script_version_payload(**overrides) -> dict:
    defaults = {
        "content_text": DEFAULTS["SCRIPT_TEXT"],
        "curriculum_standards": [],
    }
    defaults.update(overrides)
    return defaults


def review_script_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_tour_slot_payload(route_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "start_at": DEFAULTS["SLOT_START"],
    }
    defaults.update(overrides)
    return defaults


def reschedule_slot_payload(start_at, expected_slot_version) -> dict:
    return {"start_at": start_at, "expected_slot_version": expected_slot_version}


def create_docent_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["DOCENT_NAME"],
        "email": DEFAULTS["DOCENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def training_record_payload(kind, value) -> dict:
    return {"kind": kind, "value": value}


def create_shift_assignment_payload(docent_id, slot_id, shift_role="LEAD") -> dict:
    return {"docent_id": docent_id, "slot_id": slot_id, "shift_role": shift_role}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": DEFAULTS["MEMBER_EMAIL"],
        "member_number": DEFAULTS["MEMBER_NUMBER"],
        "renews_on": DEFAULTS["MEMBER_RENEWS_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_general_booking_payload(slot_id, party_size, **overrides) -> dict:
    defaults = {
        "slot_id": slot_id,
        "booking_kind": "GENERAL",
        "visitor_name": DEFAULTS["VISITOR_NAME"],
        "party_size": party_size,
    }
    defaults.update(overrides)
    return defaults


def create_member_booking_payload(slot_id, member_id, party_size, **overrides) -> dict:
    defaults = {
        "slot_id": slot_id,
        "booking_kind": "MEMBER",
        "visitor_name": DEFAULTS["MEMBER_NAME"],
        "party_size": party_size,
        "member_id": member_id,
    }
    defaults.update(overrides)
    return defaults


def create_school_booking_payload(slot_id, student_count, chaperone_count,
                                  grade_level="5", curriculum_standard="HIST-5",
                                  **overrides) -> dict:
    defaults = {
        "slot_id": slot_id,
        "booking_kind": "SCHOOL",
        "visitor_name": "Lincoln Elementary",
        "student_count": student_count,
        "chaperone_count": chaperone_count,
        "grade_level": grade_level,
        "curriculum_standard": curriculum_standard,
    }
    defaults.update(overrides)
    return defaults


def create_safety_incident_payload(room_id, severity="CRITICAL", **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "severity": severity,
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {
        "overall_rating": 5,
        "interpretation_clarity": 4,
        "would_recommend": True,
    }
    defaults.update(overrides)
    return defaults
