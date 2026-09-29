"""Entity assertions and domain invariant checkers."""

from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import METADATA_MIN_SCORE
from .types import (
    CLEARANCE_ITEM_ORDER,
    AccessLevel,
    AppointmentType,
    ClearanceStatus,
    CommitteeSeatRole,
    CommitteeSeatStatus,
    CommitteeStatus,
    DefenseEventStatus,
    DegreeLevel,
    DepositStatus,
    DocumentType,
    EmbargoReasonCode,
    EmbargoReleaseAnchor,
    EmbargoStatus,
    FormatReviewStatus,
    IntegrityScreeningStatus,
    PermissionMaterialType,
    PermissionRecordStatus,
    PermissionRightsBasis,
    ProjectionVariant,
    RoomStatus,
    TermStatus,
    ThesisIntegrityState,
    ThesisWorkflowState,
)


def _values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, label: str = "row") -> None:
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_term(data: dict) -> None:
    assert_common_fields(data, "Term")
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in _values(TermStatus)
    assert isinstance(data["announcement_lead_business_days"], int)
    assert data["announcement_lead_business_days"] >= 1
    assert isinstance(data["conferred_count"], int)
    assert data["conferred_count"] >= 0
    for field in (
        "defense_deadline",
        "format_review_deposit_deadline",
        "degree_conferral_date",
    ):
        assert isinstance(data[field], str) and data[field], f"Term.{field} required"


def assert_student(data: dict) -> None:
    assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["degree_level"] in _values(DegreeLevel)
    assert isinstance(data["program_code"], str)
    assert data["graduation_clearance_state"] in _values(ClearanceStatus)
    assert isinstance(data["degree_conferred"], bool)
    assert data.get("transcript_notation") is None or isinstance(
        data["transcript_notation"], str
    )


def assert_faculty_member(data: dict) -> None:
    assert_common_fields(data, "FacultyMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["appointment_type"] in _values(AppointmentType)
    assert isinstance(data["graduate_faculty_certified"], bool)
    assert isinstance(data["active_chair_load"], int)
    assert data["active_chair_load"] >= 0


def assert_defense_room(data: dict) -> None:
    assert_common_fields(data, "DefenseRoom")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["building"], str)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["status"] in _values(RoomStatus)
    assert isinstance(data["booked_minutes_total"], int)
    assert data["booked_minutes_total"] >= 0


def assert_thesis(data: dict) -> None:
    assert_common_fields(data, "Thesis")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["term_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["document_type"] in _values(DocumentType)
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["third_party_item_count"], int)
    assert data["third_party_item_count"] >= 0
    assert data["workflow_state"] in _values(ThesisWorkflowState)
    assert data["integrity_state"] in _values(ThesisIntegrityState)
    for counter in (
        "format_cycle_count",
        "documented_permission_count",
        "analyst_turnaround_bdays_total",
    ):
        assert isinstance(data[counter], int), f"Thesis.{counter} must be an integer"
        assert data[counter] >= 0, f"Thesis.{counter} must not be negative"


def assert_committee(data: dict) -> None:
    assert_common_fields(data, "Committee")
    assert is_valid_uuid(data["thesis_id"])
    assert data["status"] in _values(CommitteeStatus)
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert isinstance(data["external_member_count"], int)
    assert data["external_member_count"] >= 0
    assert data["external_member_count"] <= data["member_count"]


def assert_committee_member(data: dict) -> None:
    assert_common_fields(data, "CommitteeMember")
    assert is_valid_uuid(data["committee_id"])
    assert is_valid_uuid(data["faculty_id"])
    assert data["role"] in _values(CommitteeSeatRole)
    assert data["status"] in _values(CommitteeSeatStatus)


def assert_defense_event(data: dict) -> None:
    assert_common_fields(data, "DefenseEvent")
    assert is_valid_uuid(data["thesis_id"])
    assert is_valid_uuid(data["room_id"])
    assert data["status"] in _values(DefenseEventStatus)
    assert isinstance(data["scheduled_start"], str) and data["scheduled_start"]
    assert isinstance(data["scheduled_end"], str) and data["scheduled_end"]


def assert_format_review(data: dict) -> None:
    assert_common_fields(data, "FormatReview")
    assert is_valid_uuid(data["thesis_id"])
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert data["status"] in _values(FormatReviewStatus)
    for counter in (
        "critical_defect_count",
        "major_defect_count",
        "minor_defect_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["severity_weighted_defect_score"], (int, float))
    assert data["severity_weighted_defect_score"] >= 0


def assert_embargo_request(data: dict) -> None:
    assert_common_fields(data, "EmbargoRequest")
    assert is_valid_uuid(data["thesis_id"])
    assert data["reason_code"] in _values(EmbargoReasonCode)
    assert isinstance(data["requested_months"], int) and data["requested_months"] >= 1
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["status"] in _values(EmbargoStatus)
    assert isinstance(data["info_request_count"], int)
    assert data["info_request_count"] >= 0
    if data.get("release_anchor") is not None:
        assert data["release_anchor"] in _values(EmbargoReleaseAnchor)


def assert_permission_record(data: dict) -> None:
    assert_common_fields(data, "PermissionRecord")
    assert is_valid_uuid(data["thesis_id"])
    assert data["material_type"] in _values(PermissionMaterialType)
    assert data["rights_basis"] in _values(PermissionRightsBasis)
    assert isinstance(data["page_reference"], str) and data["page_reference"]
    assert data["status"] in _values(PermissionRecordStatus)


def assert_integrity_screening(data: dict) -> None:
    assert_common_fields(data, "IntegrityScreening")
    assert is_valid_uuid(data["thesis_id"])
    assert data["status"] in _values(IntegrityScreeningStatus)
    assert 0 <= data["similarity_pct"] <= 100
    assert 0 <= data["adjusted_similarity_pct"] <= 100
    assert is_iso8601_timestamp(data["screened_at"])


def assert_repository_deposit(data: dict) -> None:
    assert_common_fields(data, "RepositoryDeposit")
    assert is_valid_uuid(data["thesis_id"])
    assert isinstance(data["handle"], str) and "/" in data["handle"]
    assert data["status"] in _values(DepositStatus)
    assert data["access_level"] in _values(AccessLevel)
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data["metadata_completeness_score"] >= METADATA_MIN_SCORE
    assert isinstance(data["depositor_user_id"], str) and data["depositor_user_id"]
    assert is_iso8601_timestamp(data["deposited_at"])


def assert_graduation_clearance(data: dict) -> None:
    assert_common_fields(data, "GraduationClearance")
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in _values(ClearanceStatus)
    assert data["projection_variant"] in _values(ProjectionVariant)
    assert isinstance(data["outstanding_items"], list)
    for item in data["outstanding_items"]:
        assert item in CLEARANCE_ITEM_ORDER, f"unexpected outstanding item {item}"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 instant to whole seconds with a trailing Z.

    Derived instants are carried to whole seconds while stored timestamps are
    rendered with three fractional digits, so comparisons are made on the
    second-precision form.
    """
    assert isinstance(value, str) and value, f"expected an instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    if "." in text:
        text = text.split(".", 1)[0]
    return f"{text}Z"


def assert_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same second."""
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_outstanding_items_in_fixed_order(items: List[str]) -> None:
    """The projection emits unsatisfied items in one fixed order (PRD §3.9)."""
    positions = [CLEARANCE_ITEM_ORDER.index(item) for item in items]
    assert positions == sorted(
        positions
    ), f"outstanding_items must follow the fixed order, got {items}"


def assert_handle_format(handle: str, term_code: str, sequence: int) -> None:
    """The handle is the term code, a slash and a five-digit sequence (PRD §3.8)."""
    assert handle == f"{term_code}/{sequence:05d}", (
        f"Expected handle {term_code}/{sequence:05d}, got {handle}"
    )


def assert_conferral_notation(
    notation: str,
    document_type: str,
    deposited_date: str,
    embargo_release_date: Optional[str] = None,
) -> None:
    """The conferral notation is an exact string (PRD §3.9)."""
    expected = f"{document_type} deposited {deposited_date}"
    if embargo_release_date:
        expected += f"; access restricted until {embargo_release_date}"
    assert notation == expected, f"Expected notation {expected!r}, got {notation!r}"


def assert_chair_load_conserved(faculty_rows: List[dict], expected_total: int) -> None:
    """Summing active_chair_load over faculty equals the counted chair seats (§2.10)."""
    total = sum(row["active_chair_load"] for row in faculty_rows)
    assert total == expected_total, (
        f"Expected total active_chair_load {expected_total}, got {total}"
    )
