"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Each assert_{entity}() checks only the properties every PRD reader derives:
server-minted UUID id, ISO 8601 timestamps, enum membership, and the input
fields' presence/types. Rule-bearing field values are asserted in the tests.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    CaseStatus,
    ConferenceStatus,
    AppealStatus,
    HearingStatus,
    EvidenceStatus,
    MdrStatus,
    PlacementStatus,
    ReEntryPlanStatus,
    ExpungementStatus,
    NoticeStatus,
    DemographicGroup,
    DisabilityStatus,
    EnrollmentStatus,
    OffenseCategory,
    SanctionType,
    DeliveryMethod,
    EvidenceItemType,
    MdrOrigin,
    MdrOutcome,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """PRD §2.5: id is a server-minted UUID; created_at/updated_at are ISO 8601;
    version is a system-managed integer."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_student(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["grade_level"], int) and 6 <= data["grade_level"] <= 12
    assert data["demographic_group"] in _enum_values(DemographicGroup)
    assert data["disability_status"] in _enum_values(DisabilityStatus)
    assert isinstance(data["guardian_id"], str) and len(data["guardian_id"]) > 0
    assert data["enrollment_status"] in _enum_values(EnrollmentStatus)
    assert isinstance(data["cumulative_suspension_days"], int)
    assert data["cumulative_suspension_days"] >= 0


def assert_offense_code(data: dict):
    # Static policy definition: only id + created_at are system-managed.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["category"] in _enum_values(OffenseCategory)
    assert isinstance(data["severity_level"], int) and 1 <= data["severity_level"] <= 4
    assert isinstance(data["expellable"], bool)
    assert "updated_at" not in data, "offense codes carry no updated_at (PRD §2.5)"
    assert "version" not in data, "offense codes carry no version (PRD §2.5)"


def assert_sanction_band(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["offense_code_id"], str)
    assert data["occurrence_index"] in (1, 2, 3)
    assert isinstance(data["min_days"], int) and data["min_days"] >= 0
    assert isinstance(data["max_days"], int) and data["max_days"] <= 10
    assert data["min_days"] <= data["max_days"]
    assert "updated_at" not in data, "sanction bands carry no updated_at (PRD §2.5)"
    assert "version" not in data, "sanction bands carry no version (PRD §2.5)"


def assert_discipline_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert is_iso8601_timestamp(data.get("incident_date", "")), "incident_date must be ISO 8601"
    assert isinstance(data["description"], str)
    assert isinstance(data["referrer_id"], str) and len(data["referrer_id"]) > 0
    assert data["status"] in _enum_values(CaseStatus)


def assert_suspension_notice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["delivery_method"] in _enum_values(DeliveryMethod)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("appeal_deadline", "")), "appeal_deadline must be ISO 8601"
    assert is_iso8601_timestamp(data.get("conference_deadline", "")), (
        "conference_deadline must be ISO 8601"
    )
    assert data["status"] in _enum_values(NoticeStatus)


def assert_conference(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert is_iso8601_timestamp(data.get("scheduled_at", "")), "scheduled_at must be ISO 8601"
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in _enum_values(ConferenceStatus)


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["filed_by"], str) and len(data["filed_by"]) > 0
    assert isinstance(data["grounds"], str)
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    assert data["status"] in _enum_values(AppealStatus)


def assert_expulsion_hearing(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["hearing_officer_id"], str) and len(data["hearing_officer_id"]) > 0
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "scheduled_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), "scheduled_end must be ISO 8601"
    assert data["scheduled_end"] > data["scheduled_start"], "hearing end must be after start"
    assert data["status"] in _enum_values(HearingStatus)


def assert_evidence_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["hearing_id"], str)
    assert data["item_type"] in _enum_values(EvidenceItemType)
    assert isinstance(data["description"], str)
    assert isinstance(data["submitted_by"], str) and len(data["submitted_by"]) > 0
    assert data["status"] in _enum_values(EvidenceStatus)


def assert_manifestation_determination(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["origin"] in _enum_values(MdrOrigin)
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["status"] in _enum_values(MdrStatus)
    assert data.get("outcome") is None or data["outcome"] in _enum_values(MdrOutcome)


def assert_alt_ed_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["seats_occupied"], int) and data["seats_occupied"] >= 0
    assert data["seats_occupied"] <= data["capacity"]


def assert_alt_ed_placement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["site_id"], str)
    assert is_iso8601_timestamp(data.get("start_date", "")), "start_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("planned_end_date", "")), (
        "planned_end_date must be ISO 8601"
    )
    assert data["planned_end_date"] >= data["start_date"]
    assert data["status"] in _enum_values(PlacementStatus)


def assert_re_entry_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["placement_id"], str)
    assert isinstance(data["conditions"], list)
    assert all(isinstance(c, str) for c in data["conditions"])
    assert is_iso8601_timestamp(data.get("conference_date", "")), (
        "conference_date must be ISO 8601"
    )
    assert data["status"] in _enum_values(ReEntryPlanStatus)


def assert_expungement_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["requested_by"], str) and len(data["requested_by"]) > 0
    assert data["status"] in _enum_values(ExpungementStatus)


def assert_student_ledger_invariant(student: dict, cases: list):
    """PRD §2.7: cumulative_suspension_days equals the sum of sanction_days_final
    over exactly the student's cases whose status is CONFIRMED or CLOSED."""
    expected = sum(
        c.get("sanction_days_final") or 0
        for c in cases
        if c.get("status") in (CaseStatus.CONFIRMED.value, CaseStatus.CLOSED.value)
    )
    assert student["cumulative_suspension_days"] == expected, (
        f"Ledger invariant violated: cumulative_suspension_days="
        f"{student['cumulative_suspension_days']} but SUM over CONFIRMED/CLOSED "
        f"cases is {expected}"
    )
