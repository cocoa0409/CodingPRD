"""Entity assertions and domain invariant checkers.

Each assert_* function validates the system-managed fields of PRD section 2.4
plus the entity's declared field surface and enum membership. Optional or
null-until-set fields are checked for presence-agnostic type only when set.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccessionStatus,
    AppointmentStatus,
    AssessmentStatus,
    CollectionStatus,
    ConditionGrade,
    DeedStatus,
    DisposalMethod,
    FindingAidStatus,
    ItemFormat,
    ItemStatus,
    LicenseClass,
    OrderStatus,
    ProjectStatus,
    ProposalStatus,
    RecordingRoom,
    RecordingStatus,
    ReleaseStatus,
    RequestPurpose,
    RequestStatus,
    ResearcherStatus,
    ReproFormat,
    RoomCode,
    TicketStatus,
    ZonePosture,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), \
        f"{entity}.version must be an integer"


def assert_storage_zone(data: dict):
    _assert_common_fields(data, "StorageZone")
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["temp_high_c"], (int, float))
    assert isinstance(data["temp_low_c"], (int, float))
    assert isinstance(data["humidity_high_pct"], (int, float))
    assert isinstance(data["humidity_low_pct"], (int, float))
    assert data["posture"] in [p.value for p in ZonePosture]
    assert isinstance(data["breach_streak"], int)
    assert isinstance(data["recent_readings"], list)


def assert_collection(data: dict):
    _assert_common_fields(data, "Collection")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["collection_code"], str) and data["collection_code"]
    assert isinstance(data["storage_zone_id"], str)
    assert data["status"] in [s.value for s in CollectionStatus]
    assert isinstance(data["item_count"], int)
    assert isinstance(data["published_finding_aid_present"], bool)


def assert_accession(data: dict):
    _assert_common_fields(data, "Accession")
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert isinstance(data["donor_contact"], str) and data["donor_contact"]
    assert isinstance(data["accession_date"], str)
    assert isinstance(data["lot_appraised_value_cents"], int)
    assert data["lot_appraised_value_cents"] >= 0
    assert isinstance(data["accession_number"], str)
    assert data["status"] in [s.value for s in AccessionStatus]
    assert "current_deed_id" in data


def assert_deed(data: dict):
    _assert_common_fields(data, "DeedOfGift")
    assert isinstance(data["accession_id"], str)
    assert isinstance(data["deed_version"], int) and data["deed_version"] >= 1
    assert isinstance(data["reproduction_restricted"], bool)
    assert isinstance(data["publication_license_required"], bool)
    assert data["status"] in [s.value for s in DeedStatus]


def assert_item(data: dict):
    _assert_common_fields(data, "Item")
    assert isinstance(data["accession_id"], str)
    assert isinstance(data["collection_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in [s.value for s in ItemStatus]
    if data.get("condition_grade") is not None:
        assert data["condition_grade"] in [g.value for g in ConditionGrade]
    if data.get("format") is not None:
        assert data["format"] in [f.value for f in ItemFormat]
    if data.get("appraised_value_cents") is not None:
        assert isinstance(data["appraised_value_cents"], int)
        assert data["appraised_value_cents"] >= 0
    assert "conservation_priority_score" in data
    assert "current_assessment_id" in data


def assert_assessment(data: dict):
    _assert_common_fields(data, "ConservationAssessment")
    assert isinstance(data["item_id"], str)
    assert data["condition_grade_observed"] in [g.value for g in ConditionGrade]
    assert isinstance(data["urgency_score"], int)
    assert 0 <= data["urgency_score"] <= 100
    assert isinstance(data["treatment_estimate_hours"], int)
    assert data["treatment_estimate_hours"] > 0
    assert isinstance(data["open_request_count_snapshot"], int)
    assert isinstance(data["preliminary_priority_score"], (int, float))
    assert data["status"] in [s.value for s in AssessmentStatus]
    assert "confirmed_priority_score" in data


def assert_finding_aid(data: dict):
    _assert_common_fields(data, "FindingAid")
    assert isinstance(data["collection_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["summary"], str)
    assert data["status"] in [s.value for s in FindingAidStatus]
    assert isinstance(data["published_revision_count"], int)
    assert "published_at" in data


def assert_project(data: dict):
    _assert_common_fields(data, "VolunteerProject")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_hours_per_volunteer"], int)
    assert data["status"] in [s.value for s in ProjectStatus]
    assert isinstance(data["hours_logged_total"], (int, float))
    assert isinstance(data["volunteer_hours"], dict)
    assert isinstance(data["active_ticket_count"], int)


def assert_ticket(data: dict):
    _assert_common_fields(data, "DigitizationTicket")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["item_id"], str)
    assert data["status"] in [s.value for s in TicketStatus]
    assert isinstance(data["qc_fail_count"], int)
    assert isinstance(data["hours_logged"], (int, float))
    assert "claimed_by_user_id" in data
    assert "priority_score" in data


def assert_researcher(data: dict):
    _assert_common_fields(data, "Researcher")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in [s.value for s in ResearcherStatus]
    assert isinstance(data["no_show_strikes"], int)
    assert isinstance(data["total_charged_cents"], int)


def assert_request(data: dict):
    _assert_common_fields(data, "ResearchRequest")
    assert isinstance(data["researcher_id"], str)
    assert isinstance(data["item_ids"], list) and len(data["item_ids"]) >= 1
    assert isinstance(data["topic"], str)
    assert data["purpose"] in [p.value for p in RequestPurpose]
    assert data["status"] in [s.value for s in RequestStatus]


def assert_appointment(data: dict):
    _assert_common_fields(data, "ReadingRoomAppointment")
    assert isinstance(data["researcher_id"], str)
    assert isinstance(data["research_request_id"], str)
    assert data["room_code"] in [r.value for r in RoomCode]
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["start_time"], str)
    assert isinstance(data["end_time"], str)
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert data["status"] in [s.value for s in AppointmentStatus]


def assert_order(data: dict):
    _assert_common_fields(data, "ReproductionOrder")
    assert isinstance(data["researcher_id"], str)
    assert isinstance(data["research_request_id"], str)
    assert isinstance(data["item_ids"], list) and len(data["item_ids"]) >= 1
    assert data["format"] in [f.value for f in ReproFormat]
    assert isinstance(data["page_estimate"], int) and data["page_estimate"] > 0
    assert data["license_class"] in [c.value for c in LicenseClass]
    assert isinstance(data["rush"], bool)
    assert isinstance(data["quoted_fee_cents"], int)
    assert data["status"] in [s.value for s in OrderStatus]
    assert "invoiced_fee_cents" in data


def assert_proposal(data: dict):
    _assert_common_fields(data, "DeaccessionProposal")
    assert isinstance(data["item_ids"], list) and len(data["item_ids"]) >= 1
    assert isinstance(data["justification"], str)
    assert data["disposal_method"] in [m.value for m in DisposalMethod]
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["status"] in [s.value for s in ProposalStatus]


def assert_oral_history(data: dict):
    _assert_common_fields(data, "OralHistoryRecording")
    assert isinstance(data["collection_id"], str)
    assert isinstance(data["narrator_name"], str) and data["narrator_name"]
    assert isinstance(data["interviewer_name"], str)
    assert data["recording_room_id"] in [r.value for r in RecordingRoom]
    assert isinstance(data["session_start"], str)
    assert isinstance(data["session_end"], str)
    assert data["status"] in [s.value for s in RecordingStatus]
    assert data["release_status"] in [s.value for s in ReleaseStatus]
