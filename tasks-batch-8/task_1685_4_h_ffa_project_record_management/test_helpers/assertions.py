"""Entity assertions and domain invariant checkers.

Mutable resources carry id + created_at + updated_at + version. Audit-line
resources (ledger entries, attendance rows, screening events, treasury
transactions) carry only id + created_at — the assertions below enforce that
distinction per the PRD resource-identity rules.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_mutable_resource(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_audit_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"


def assert_club(data: dict):
    _assert_mutable_resource(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["county_code"], str) and len(data["county_code"]) > 0
    assert isinstance(data["treasury_balance_cents"], int)
    assert isinstance(data["star_nomination_count"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_volunteer(data: dict):
    _assert_mutable_resource(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["base_clearance"], int)
    assert isinstance(data["risk_flags"], int)
    assert isinstance(data["years_service"], int)
    assert isinstance(data["screening_score"], int)
    assert data["screening_status"] in ("PENDING", "CLEARED", "DENIED")
    assert is_valid_uuid(data.get("club_id", ""))


def assert_member(data: dict):
    _assert_mutable_resource(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) > 0
    assert is_valid_uuid(data.get("club_id", ""))
    assert data["enrollment_status"] in ("ENROLLED", "ACTIVE", "SUSPENDED", "GRADUATED")
    assert isinstance(data["is_club_officer"], bool)
    assert data["eligibility_posture"] in ("ELIGIBLE", "CONDITIONAL", "INELIGIBLE")


def assert_project(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["project_type"] in ("BEEF", "SHEEP", "SWINE", "CROPS", "FOODS", "ROBOTICS")
    assert isinstance(data["program_year"], int)
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "DROPPED")
    assert data["grade"] in ("A", "B", "C", "NONE")


def assert_animal_tag(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["tag_number"], str) and len(data["tag_number"]) > 0
    assert data["species"] in ("BEEF", "SHEEP", "SWINE")
    assert is_iso8601_timestamp(data.get("owned_since", ""))
    assert is_iso8601_timestamp(data.get("tagged_at", ""))
    assert data["tagging_status"] in ("TAGGED", "VERIFIED", "REJECTED")


def assert_record_book(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["program_year"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED", "APPROVED", "REJECTED")
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("provisional_score") is None or isinstance(data["provisional_score"], (int, float))
    assert data.get("final_score") is None or isinstance(data["final_score"], (int, float))
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0


def assert_ledger_entry(data: dict):
    _assert_audit_line(data)
    assert is_valid_uuid(data.get("record_book_id", ""))
    assert data["entry_kind"] in ("EXPENSE", "INCOME", "HOURS")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["hours"], (int, float))
    assert data["entry_status"] in ("POSTED", "VOIDED")
    assert isinstance(data["recorded_on"], str) and len(data["recorded_on"]) > 0


def assert_meeting(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("club_id", ""))
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED")


def assert_room(data: dict):
    _assert_mutable_resource(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int)


def assert_attendance(data: dict):
    _assert_audit_line(data)
    assert is_valid_uuid(data.get("meeting_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["attendance_status"] in ("PRESENT", "ABSENT", "EXCUSED")


def assert_fair_entry(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["fair_level"] in ("COUNTY", "STATE")
    assert data["status"] in ("ENTERED", "CONFIRMED", "SCRATCHED", "EXHIBITED")
    assert data.get("ownership_days_at_entry") is None or isinstance(data["ownership_days_at_entry"], int)


def assert_stall_assignment(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("fair_entry_id", ""))
    assert is_valid_uuid(data.get("pen_id", ""))
    assert data["status"] in ("ASSIGNED", "RELEASED")


def assert_pen(data: dict):
    _assert_mutable_resource(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["animal_capacity"], int)


def assert_award_application(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["award_track"] in ("DEGREE", "STAR", "SCHOLARSHIP")
    assert is_valid_uuid(data.get("record_book_id", ""))
    assert data["status"] in ("DRAFT", "NOMINATED", "ENDORSED", "EVALUATED", "AWARDED", "DENIED", "WITHDRAWN")
    assert data.get("rubric_score") is None or isinstance(data["rubric_score"], (int, float))
    assert data.get("award_tier") is None or data["award_tier"] in ("GOLD", "SILVER", "BRONZE", "NONE")


def assert_scholarship_app(data: dict):
    _assert_mutable_resource(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("linked_award_application_id", ""))
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "GRANTED", "DECLINED")
    assert data.get("scholarship_points") is None or isinstance(data["scholarship_points"], int)


def assert_screening_event(data: dict):
    _assert_audit_line(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["event_kind"] in ("BACKGROUND_CHECK", "REFERENCE_CHECK", "INTERVIEW")
    assert data["outcome"] in ("PASS", "FLAG", "FAIL")


def assert_treasury_transaction(data: dict):
    _assert_audit_line(data)
    assert is_valid_uuid(data.get("club_id", ""))
    assert data["txn_kind"] in ("DUES_PAYMENT", "EXPENSE_REIMBURSEMENT")
    assert isinstance(data["amount_cents"], int)
    assert data["txn_status"] in ("POSTED", "APPROVED", "VOIDED")
