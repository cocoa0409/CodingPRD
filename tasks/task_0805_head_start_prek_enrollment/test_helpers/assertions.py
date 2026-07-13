"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields for entities that carry them (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert data["program_type"] in ("HEAD_START", "PRE_K", "EARLY_HEAD_START")
    assert isinstance(data["funded_enrollment"], int) and data["funded_enrollment"] >= 0
    assert isinstance(data["total_instructional_days"], int) and data["total_instructional_days"] > 0


def assert_cohort(data: dict):
    _assert_common(data)
    assert data["age_band"] in ("INFANT", "TODDLER", "PRESCHOOL_3", "PRESCHOOL_4")
    assert data["selection_status"] in ("OPEN", "FULL")
    assert_cohort_slot_invariants(data)


def assert_cohort_slot_invariants(data: dict):
    """Cohort slot accounting invariants (PRD §2.5)."""
    assert data["filled_slots"] >= 0
    assert data["reserved_slots"] >= 0
    assert data["available_slots"] >= 0, "available_slots is never negative by construction"
    assert data["available_slots"] == (
        data["funded_slots"] - data["filled_slots"] - data["reserved_slots"]
    ), "available_slots == funded_slots - filled_slots - reserved_slots"
    expected_sel = "OPEN" if data["available_slots"] > 0 else "FULL"
    assert data["selection_status"] == expected_sel, (
        "selection_status is OPEN when available_slots > 0 else FULL"
    )


def assert_family(data: dict):
    _assert_common(data)
    assert data["categorical_eligibility"] in ("NONE", "TANF", "SSI", "SNAP", "FOSTER")
    assert isinstance(data["homeless_status"], bool)
    assert data["household_size"] >= 1


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ELIGIBLE", "INELIGIBLE",
        "WAITLISTED", "OFFERED", "ENROLLED", "WITHDRAWN",
    )


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "COMPLETED_TRANSITION", "WITHDRAWN", "DISENROLLED")
    assert data["health_compliance_status"] in ("PENDING", "COMPLIANT", "NON_COMPLIANT", "EXEMPT")


def assert_attendance_record(data: dict):
    """AttendanceRecord is append-only: only id + created_at, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")


def assert_health_screening(data: dict):
    _assert_common(data)
    assert data["screening_type"] in ("IMMUNIZATION", "PHYSICAL", "DENTAL")
    assert data["status"] in ("DUE", "UP_TO_DATE", "OVERDUE", "EXEMPT")


def assert_home_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")


def assert_transition_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "COMPLETED", "CANCELLED")


def assert_pir_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED")
