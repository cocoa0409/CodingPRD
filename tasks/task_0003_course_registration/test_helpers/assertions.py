"""Entity assertions and domain invariant checkers (PRD-faithful)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, entity_label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be a positive integer"


def _assert_append_only_fields(data: dict, entity_label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"


# ─── Common-fields entities ────────────────────────────────────────────
def assert_department(data: dict) -> None:
    _assert_common_fields(data, "Department")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["campus_id"], str) and len(data["campus_id"]) > 0
    assert data["status"] in ("ACTIVE", "DISSOLVED")


def assert_campus(data: dict) -> None:
    _assert_common_fields(data, "Campus")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["commute_minutes_to"], dict)


def assert_student(data: dict) -> None:
    _assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["program_id"], str)
    assert isinstance(data["program_department_id"], str)
    assert isinstance(data["home_campus_id"], str)
    assert isinstance(data["year_in_program"], int)
    assert 1 <= data["year_in_program"] <= 6
    assert isinstance(data["gpa"], (int, float))
    assert 0.0 <= float(data["gpa"]) <= 4.0
    assert isinstance(data["fraud_score"], int) and data["fraud_score"] >= 0
    assert isinstance(data["completed_course_ids"], list)
    assert data["status"] in ("ENROLLED", "SUSPENDED", "GRADUATED")


def assert_professor(data: dict) -> None:
    _assert_common_fields(data, "Professor")
    assert isinstance(data["department_id"], str) and len(data["department_id"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["rank"] in ("ASSISTANT", "ASSOCIATE", "FULL")
    assert isinstance(data["is_chair"], bool)
    if data["is_chair"]:
        assert data["rank"] in ("ASSOCIATE", "FULL"), \
            "Chairs must hold rank ASSOCIATE or FULL (PRD §3.6)"
    assert isinstance(data["max_concurrent_teaching_minutes_per_week"], int)


def assert_term(data: dict) -> None:
    _assert_common_fields(data, "Term")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for key in ("registration_open_at", "registration_close_at", "classes_start_at",
                "exam_window_start_at", "exam_window_end_at"):
        assert isinstance(data[key], int), f"Term.{key} must be integer Unix seconds"
    assert data["status"] in ("PLANNING", "REGISTRATION_OPEN", "REGISTRATION_CLOSED",
                               "IN_SESSION", "CONCLUDED")


def assert_course(data: dict) -> None:
    _assert_common_fields(data, "Course")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["credits"], (int, float))
    assert float(data["credits"]) > 0
    assert isinstance(data["owning_department_id"], str)
    assert isinstance(data["prerequisite_course_ids"], list)
    assert isinstance(data["equivalent_course_ids"], list)


def assert_course_offering(data: dict) -> None:
    _assert_common_fields(data, "CourseOffering")
    assert isinstance(data["term_id"], str)
    assert isinstance(data["course_id"], str)
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert isinstance(data["base_capacity"], int) and data["base_capacity"] >= 1
    assert isinstance(data["capacity"], int)
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["scheduled_meetings"], list)
    assert isinstance(data["requires_lab_equipment_ids"], list)
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED", "IN_SESSION", "CONCLUDED")
    # Invariant per PRD §3.3: enrolled_count <= capacity at all times after scaling completes.
    assert data["enrolled_count"] <= data["capacity"], \
        f"Invariant breach: enrolled_count={data['enrolled_count']} > capacity={data['capacity']}"


def assert_lab_equipment(data: dict) -> None:
    _assert_common_fields(data, "LabEquipment")
    assert isinstance(data["campus_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["setup_buffer_minutes"], int) and data["setup_buffer_minutes"] >= 0


def assert_enrollment_request(data: dict) -> None:
    _assert_common_fields(data, "EnrollmentRequest")
    assert isinstance(data["student_id"], str)
    assert isinstance(data["offering_id"], str)
    assert isinstance(data["term_id"], str)
    assert data["academic_status"] in ("SUBMITTED", "APPROVED", "WAITLISTED",
                                         "REJECTED", "CANCELED", "SETTLED")
    assert data["financial_status"] in ("UNBILLED", "BILLED", "PAID")


def assert_over_limit_application(data: dict) -> None:
    _assert_common_fields(data, "OverLimitApplication")
    assert isinstance(data["student_id"], str)
    assert isinstance(data["term_id"], str)
    assert isinstance(data["requested_extension_credits"], (int, float))
    assert float(data["requested_extension_credits"]) > 0
    assert isinstance(data["justification"], str)
    assert isinstance(data["primary_signer_id"], str)
    assert isinstance(data["secondary_signer_id"], str)
    assert isinstance(data["granted_credits"], (int, float))
    assert data["status"] in ("DRAFT", "AWAITING_PRIMARY", "AWAITING_SECONDARY",
                               "APPROVED", "REJECTED", "EXPIRED")


def assert_department_access_grant(data: dict) -> None:
    _assert_common_fields(data, "DepartmentAccessGrant")
    assert isinstance(data["source_department_id"], str)
    assert isinstance(data["target_department_id"], str)
    assert isinstance(data["course_categories_allowed"], list)
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["bidirectional"], bool)


# ─── Append-only entities (no version, no updated_at) ───────────────────
def assert_waitlist_entry(data: dict) -> None:
    _assert_append_only_fields(data, "WaitlistEntry")
    assert isinstance(data["offering_id"], str)
    assert isinstance(data["enrollment_request_id"], str)
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["queued_at"], int)
    assert data["status"] in ("ACTIVE", "PROMOTED", "EXPIRED", "CANCELED")
    assert "updated_at" not in data, "WaitlistEntry must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "WaitlistEntry must not carry version (PRD §2.4)"


def assert_credit_equivalence_policy(data: dict) -> None:
    _assert_append_only_fields(data, "CreditEquivalencePolicy")
    assert isinstance(data["source_program_id"], str)
    assert isinstance(data["target_program_id"], str)
    assert isinstance(data["source_course_id"], str)
    assert isinstance(data["target_course_id"], str)
    assert isinstance(data["transfer_factor"], (int, float))
    assert 0 < float(data["transfer_factor"]) <= 1.0
    assert "updated_at" not in data, "CreditEquivalencePolicy must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "CreditEquivalencePolicy must not carry version (PRD §2.4)"


def assert_sync_event(data: dict) -> None:
    _assert_append_only_fields(data, "SyncEvent")
    assert isinstance(data["subject_entity"], str)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["event_type"], str)
    assert data["event_type"] in (
        "ENROLLMENT_APPROVED", "ENROLLMENT_CANCELED", "TUITION_BILLED",
        "TUITION_PAID", "OVER_LIMIT_GRANTED", "CAPACITY_REDUCED_CANCELED",
        "WAITLIST_PROMOTED",
    )
    assert isinstance(data["target_systems"], list)
    for sys_name in data["target_systems"]:
        assert sys_name in ("ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"), \
            f"Unexpected target system: {sys_name}"
    assert isinstance(data["payload"], dict)


# ─── Domain invariants ─────────────────────────────────────────────────
def assert_credit_precision(value: float, label: str = "credits") -> None:
    """Credit-hour quantities are stored to two decimal places (PRD §2.5)."""
    assert isinstance(value, (int, float)), f"{label} must be numeric"
    assert round(float(value), 2) == round(float(value), 6), \
        f"{label} must have at most two decimal places, got {value!r}"


def assert_offering_capacity_invariant(offering: dict) -> None:
    """PRD §3.3: enrolled_count must not exceed capacity at any time after scaling."""
    assert offering["enrolled_count"] <= offering["capacity"], (
        f"Capacity invariant breach on offering {offering.get('id')}: "
        f"enrolled_count={offering['enrolled_count']} > capacity={offering['capacity']}"
    )


def find_sync_event(events: list, event_type: str) -> dict:
    """Return the first SyncEvent matching event_type, or raise."""
    for e in events:
        if e.get("event_type") == event_type:
            return e
    raise AssertionError(
        f"No SyncEvent of type {event_type!r} found among "
        f"{[e.get('event_type') for e in events]}"
    )


def has_sync_event(events: list, event_type: str) -> bool:
    return any(e.get("event_type") == event_type for e in events)
