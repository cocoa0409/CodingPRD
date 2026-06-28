"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

VISA_STATES = {"NONE", "INITIAL", "ACTIVE", "PROBATION", "TERMINATED"}
CERT_STATES = {"NONE", "PROVISIONAL", "CERTIFIED", "VOIDED"}
TRACKS = {"GENERAL", "ACADEMIC", "BUSINESS", "EXAM_PREP"}
LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
ENROLLMENT_STATES = {
    "PLACEMENT_PENDING", "ENROLLED", "WAITLISTED", "COMPLETED", "WITHDRAWN", "TERMINATED",
}
PT_STATES = {"REGISTERED", "SCORED", "VOIDED"}
COHORT_STATES = {"OPEN", "FULL"}
CONTRACT_STATES = {"ACTIVE", "EXHAUSTED", "CLOSED"}
ADDON_STATES = {"ACTIVE", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_common(data: dict):
    """For common_fields:false entities — id + created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must NOT carry a version field"
    assert "updated_at" not in data, "append-only entity must NOT carry an updated_at field"


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["is_international"], bool)
    assert data["visa_status"] in VISA_STATES, f"unexpected visa_status {data['visa_status']!r}"
    assert data["certification_status"] in CERT_STATES
    assert data["track"] in TRACKS
    assert data["placement_level"] is None or data["placement_level"] in LEVELS
    assert isinstance(data["i20_required_weekly_hours"], int)


def assert_corporate_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contracted_seats"], int) and data["contracted_seats"] >= 1
    assert isinstance(data["seats_consumed"], int) and data["seats_consumed"] >= 0
    assert data["discount_tier"] in {"BRONZE", "SILVER", "GOLD"}
    assert data["status"] in CONTRACT_STATES


def assert_placement_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in PT_STATES
    assert data["assigned_level"] is None or data["assigned_level"] in LEVELS


def assert_cohort(data: dict):
    _assert_common(data)
    assert data["level"] in LEVELS
    assert data["track"] in TRACKS
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["weekly_hours"], int) and data["weekly_hours"] >= 1
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert data["status"] in COHORT_STATES
    assert data["schedule_block"] in {"MORNING", "AFTERNOON", "EVENING"}
    assert isinstance(data["base_tuition_cents"], int) and data["base_tuition_cents"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["cohort_id"])
    assert data["status"] in ENROLLMENT_STATES
    assert isinstance(data["sessions_attended"], int)
    assert isinstance(data["sessions_elapsed"], int)
    assert isinstance(data["attendance_rate"], (int, float))
    assert 0.0 <= float(data["attendance_rate"]) <= 1.0
    assert isinstance(data["tuition_invoice_cents"], int)
    assert isinstance(data["refund_cents"], int)


def assert_progress_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    for k in ("speaking", "listening", "reading", "writing"):
        assert isinstance(data[k], int) and 0 <= data[k] <= 100


def assert_add_on(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["add_on_type"] in {"CONVERSATION_CLUB", "PRIVATE_TUTORING", "IMMERSION_ABROAD"}
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ADDON_STATES


def assert_attendance_record(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["session_index"], int) and data["session_index"] >= 1
    assert data["status"] in {"PRESENT", "ABSENT", "EXCUSED"}


def assert_compliance_event(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["student_id"])
    assert data["event_type"] in {
        "I20_ISSUED", "STATUS_ACTIVATED", "PROBATION_PLACED", "PROBATION_CLEARED", "I20_TERMINATED",
    }
    assert data["prior_status"] in VISA_STATES
    assert data["new_status"] in VISA_STATES


# ---- Domain invariant checkers ----
def assert_cohort_seat_invariant(data: dict):
    """seats_taken in [0, capacity]; status OPEN below capacity, FULL at capacity."""
    assert 0 <= data["seats_taken"] <= data["capacity"], (
        f"seats_taken {data['seats_taken']} out of [0, {data['capacity']}]"
    )
    if data["seats_taken"] == data["capacity"]:
        assert data["status"] == "FULL"
    else:
        assert data["status"] == "OPEN"


def assert_contract_seat_invariant(data: dict):
    """seats_consumed in [0, contracted_seats]."""
    assert 0 <= data["seats_consumed"] <= data["contracted_seats"], (
        f"seats_consumed {data['seats_consumed']} out of [0, {data['contracted_seats']}]"
    )
