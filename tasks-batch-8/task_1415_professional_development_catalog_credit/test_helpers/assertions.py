"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §2.7, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, label: str):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_building(data: dict):
    _assert_common(data, "Building")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_employee(data: dict):
    _assert_common(data, "Employee")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["employee_kind"] in ("TEACHER", "ADMIN", "SPECIALIST")
    assert is_valid_uuid(data.get("primary_building_id", ""))
    assert data["base_lane"] in ("BA", "BA15", "MA", "MA15", "MA30", "DOC")
    assert data["current_lane"] in ("BA", "BA15", "MA", "MA15", "MA30", "DOC")
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "SEPARATED")
    assert isinstance(data["lane_credit_balance"], (int, float))
    assert data["compliance_standing"] in ("COMPLIANT", "NON_COMPLIANT")


def assert_budget(data: dict):
    _assert_common(data, "BuildingBudget")
    assert is_valid_uuid(data.get("building_id", ""))
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["allocated_cents"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    assert isinstance(data["encumbered_cents"], int)
    assert isinstance(data["spent_cents"], int)


def assert_course(data: dict):
    _assert_common(data, "Course")
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["delivery_mode"] in ("IN_PERSON", "VIRTUAL", "HYBRID")
    assert data["clock_hours"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_section(data: dict):
    _assert_common(data, "Section")
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "REGISTRATION_CLOSED",
                              "IN_SESSION", "COMPLETED", "CANCELED")
    assert isinstance(data["seats_registered"], int)
    assert isinstance(data["seats_open"], int)


def assert_meeting(data: dict):
    _assert_common(data, "SectionMeeting")
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))


def assert_registration(data: dict):
    _assert_common(data, "Registration")
    assert is_valid_uuid(data.get("teacher_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert data["status"] in ("REGISTERED", "WAITLISTED", "DROPPED", "WITHDRAWN",
                              "EXPIRED", "NO_SHOW", "COMPLETED")
    assert data["attendance_status"] in ("PENDING", "VERIFIED", "ABSENT")
    assert data["survey_status"] in ("PENDING", "SUBMITTED", "WAIVED")


def assert_transcript_entry(data: dict):
    _assert_common(data, "TranscriptEntry")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["source_type"] in ("COURSE_COMPLETION", "EXTERNAL_WORKSHOP", "AUDIT_REVERSAL")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["clock_hours"], (int, float))
    assert isinstance(data["district_credit"], (int, float))
    assert isinstance(data["state_ceu"], (int, float))
    assert isinstance(data["counts_toward_lane"], bool)
    assert data["status"] in ("AWARDED", "REVERSED")


def assert_workshop(data: dict):
    _assert_common(data, "ExternalWorkshopRequest")
    assert is_valid_uuid(data.get("teacher_id", ""))
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ATTENDED",
                              "REIMBURSED", "REIMBURSEMENT_DENIED", "EXPIRED")
    assert isinstance(data["est_cost_cents"], int) and data["est_cost_cents"] > 0
    assert isinstance(data["revision_count"], int)


def assert_growth_plan(data: dict):
    _assert_common(data, "GrowthPlan")
    assert is_valid_uuid(data.get("teacher_id", ""))
    assert isinstance(data["school_year"], str)
    assert isinstance(data["focus_areas"], list) and len(data["focus_areas"]) > 0
    assert data["target_credits"] > 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "FULFILLED",
                              "CLOSED", "SUPERSEDED")


def assert_assignment(data: dict):
    _assert_common(data, "ComplianceAssignment")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data["status"] in ("ASSIGNED", "IN_PROGRESS", "SATISFIED", "OVERDUE",
                              "ESCALATED", "WAIVED")
    assert isinstance(data["extension_count"], int)


def assert_audit_case(data: dict):
    _assert_common(data, "AuditCase")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["fiscal_year"], int)
    assert data["status"] in ("OPEN", "FINDINGS_RAISED", "RESOLVED", "CLOSED_CLEAN")
    assert isinstance(data["findings_count"], int)


def assert_budget_conservation(budget: dict):
    """PRD §2.7 standing invariant: allocation == encumbered + spent + available."""
    total = budget["encumbered_cents"] + budget["spent_cents"] + budget["available_cents"]
    assert budget["allocated_cents"] == total, (
        f"Budget conservation violated: {budget['allocated_cents']} != "
        f"{budget['encumbered_cents']} + {budget['spent_cents']} + {budget['available_cents']}"
    )


def assert_seat_conservation(section: dict):
    """PRD §3.2: seats_open is the capacity minus the REGISTERED count."""
    assert section["seat_capacity"] == section["seats_registered"] + section["seats_open"], (
        f"Seat conservation violated: {section['seat_capacity']} != "
        f"{section['seats_registered']} + {section['seats_open']}"
    )
