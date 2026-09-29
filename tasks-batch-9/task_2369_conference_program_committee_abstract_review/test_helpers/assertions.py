"""Entity-shape assertions and conserved-quantity invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbstractStatus,
    AccreditationPosture,
    AccreditationValidationStatus,
    AuthorSanctionStatus,
    ChangeRequestStatus,
    ChangeType,
    CoiDeclarationStatus,
    CommitteeMemberStatus,
    ConferenceStatus,
    ConflictSubjectType,
    ConflictType,
    DiscrepancyCaseStatus,
    DisclosureStatementStatus,
    EmbargoStatus,
    MemberRole,
    PresentationFormat,
    ReviewStatus,
    SessionSlotStatus,
    SessionStatus,
)


def _assert_common_fields(data: dict, entity_name: str) -> None:
    """id + created_at + updated_at + version, per the PRD's common properties."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_name}.version must be an integer"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_conference(data: dict) -> None:
    _assert_common_fields(data, "Conference")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in _values(ConferenceStatus)
    for field in (
        "event_start_utc",
        "event_end_utc",
        "abstract_deadline_utc",
        "review_deadline_utc",
        "program_freeze_utc",
    ):
        assert is_iso8601_timestamp(data[field]), f"Conference.{field} must be ISO 8601"
    for field in (
        "oral_slot_capacity",
        "poster_slot_capacity",
        "workshop_slot_capacity",
        "accepted_oral_count",
        "accepted_poster_count",
        "accepted_workshop_count",
        "waitlisted_count",
        "cme_minutes_pool_total",
        "cme_minutes_allocated",
        "cme_minutes_available",
        "cfa_extension_count",
        "review_reopen_count",
        "abstract_sequence",
    ):
        assert isinstance(data[field], int), f"Conference.{field} must be an integer"
        assert data[field] >= 0, f"Conference.{field} must not go negative"


def assert_category(data: dict) -> None:
    _assert_common_fields(data, "SubmissionCategory")
    assert isinstance(data["allowed_formats"], list) and data["allowed_formats"]
    for fmt in data["allowed_formats"]:
        assert fmt in _values(PresentationFormat)
    assert 100 <= data["max_word_count"] <= 600
    assert 2 <= data["min_reviews_required"] <= 5
    assert 0.50 <= float(data["discrepancy_threshold"]) <= 4.00
    assert isinstance(data["cme_eligible"], bool)
    assert isinstance(data["requires_structured_body"], bool)


def assert_author(data: dict) -> None:
    _assert_common_fields(data, "Author")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["is_registered"], bool)
    assert data["sanction_status"] in _values(AuthorSanctionStatus)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert (
        isinstance(data["embargo_breach_count"], int)
        and data["embargo_breach_count"] >= 0
    )


def assert_abstract(data: dict) -> None:
    _assert_common_fields(data, "Abstract")
    assert is_valid_uuid(data["conference_id"])
    assert is_valid_uuid(data["category_id"])
    assert is_valid_uuid(data["submitting_author_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["body_word_count"], int) and data["body_word_count"] >= 1
    assert data["requested_format"] in _values(PresentationFormat)
    assert isinstance(data["keywords"], list) and 1 <= len(data["keywords"]) <= 5
    assert data["status"] in _values(AbstractStatus)
    assert data["embargo_status"] in _values(EmbargoStatus)
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 2
    assert (
        isinstance(data["submitted_review_count"], int)
        and data["submitted_review_count"] >= 0
    )


def assert_committee_member(data: dict) -> None:
    _assert_common_fields(data, "CommitteeMember")
    assert is_valid_uuid(data["conference_id"])
    assert data["member_role"] in _values(MemberRole)
    assert data["status"] in _values(CommitteeMemberStatus)
    assert data["coi_declaration_status"] in _values(CoiDeclarationStatus)
    assert isinstance(data["expertise_keywords"], list) and data["expertise_keywords"]
    assert 1 <= data["max_review_load"] <= 20
    assert -1.00 <= float(data["calibration_bias"]) <= 1.00
    assert_reviewer_load_within_ceiling(data)


def assert_conflict_declaration(data: dict) -> None:
    """A conflict declaration is append-only: only id and created_at are common."""
    assert is_valid_uuid(data.get("id", "")), "ConflictDeclaration.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "ConflictDeclaration.created_at must be an ISO 8601 timestamp"
    assert is_valid_uuid(data["member_id"])
    assert data["conflict_subject_type"] in _values(ConflictSubjectType)
    assert data["conflict_type"] in _values(ConflictType)
    assert is_iso8601_timestamp(data["declared_at"])


def assert_review(data: dict) -> None:
    _assert_common_fields(data, "Review")
    assert is_valid_uuid(data["abstract_id"])
    assert is_valid_uuid(data["reviewer_member_id"])
    assert data["status"] in _values(ReviewStatus)
    assert isinstance(data["assigned_round"], int) and data["assigned_round"] >= 0
    assert isinstance(data["is_third_review"], bool)
    assert is_iso8601_timestamp(data["due_utc"])


def assert_discrepancy_case(data: dict) -> None:
    _assert_common_fields(data, "DiscrepancyCase")
    assert is_valid_uuid(data["abstract_id"])
    assert data["status"] in _values(DiscrepancyCaseStatus)


def assert_session(data: dict) -> None:
    _assert_common_fields(data, "Session")
    assert is_valid_uuid(data["conference_id"])
    assert is_valid_uuid(data["chair_member_id"])
    assert data["format"] in _values(PresentationFormat)
    assert data["status"] in _values(SessionStatus)
    assert data["accreditation_posture"] in _values(AccreditationPosture)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert 1 <= data["capacity_slots"] <= 20
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 0
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_session_slot(data: dict) -> None:
    _assert_common_fields(data, "SessionSlot")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["abstract_id"])
    assert is_valid_uuid(data["presenter_author_id"])
    assert data["status"] in _values(SessionSlotStatus)
    assert 1 <= data["position"] <= 20
    assert 5 <= data["duration_minutes"] <= 120


def assert_accreditation(data: dict) -> None:
    _assert_common_fields(data, "CmeAccreditation")
    assert is_valid_uuid(data["abstract_id"])
    assert 5 <= data["content_minutes"] <= 240
    assert data["validation_status"] in _values(AccreditationValidationStatus)
    assert isinstance(data["commercial_bias_flag"], bool)
    assert_quarter_credit_step(data["awarded_credits"])


def assert_disclosure_statement(data: dict) -> None:
    _assert_common_fields(data, "DisclosureStatement")
    assert is_valid_uuid(data["abstract_id"])
    assert is_valid_uuid(data["accreditation_id"])
    assert is_valid_uuid(data["author_id"])
    assert isinstance(data["has_financial_relationship"], bool)
    assert isinstance(data["mitigation_required"], bool)
    assert data["status"] in _values(DisclosureStatementStatus)


def assert_program_change_request(data: dict) -> None:
    _assert_common_fields(data, "ProgramChangeRequest")
    assert is_valid_uuid(data["session_slot_id"])
    assert data["change_type"] in _values(ChangeType)
    assert data["status"] in _values(ChangeRequestStatus)
    assert isinstance(data["estimated_fee_cents"], int)
    assert data["estimated_fee_cents"] >= 0


# ─── Conserved-quantity invariants ───────────────────────────────────────


def assert_reviewer_load_within_ceiling(member: dict) -> None:
    """The PRD keeps current_review_load between zero and max_review_load."""
    load = member["current_review_load"]
    ceiling = member["max_review_load"]
    assert isinstance(load, int), "current_review_load must be an integer"
    assert 0 <= load <= ceiling, (
        f"current_review_load {load} must stay between 0 and max_review_load {ceiling}"
    )


def assert_format_capacity_within_bounds(conference: dict) -> None:
    """Accepted counts never exceed the declared slot capacities."""
    for fmt in ("oral", "poster", "workshop"):
        accepted = conference[f"accepted_{fmt}_count"]
        capacity = conference[f"{fmt}_slot_capacity"]
        assert accepted <= capacity, (
            f"accepted_{fmt}_count {accepted} must not exceed "
            f"{fmt}_slot_capacity {capacity}"
        )


def assert_cme_pool_conserved(conference: dict) -> None:
    """Allocated plus available minutes always reconstruct the declared pool."""
    total = conference["cme_minutes_pool_total"]
    allocated = conference["cme_minutes_allocated"]
    available = conference["cme_minutes_available"]
    assert allocated >= 0, "cme_minutes_allocated must not go negative"
    assert available >= 0, "cme_minutes_available must not go negative"
    assert allocated + available == total, (
        f"cme_minutes_allocated {allocated} + cme_minutes_available {available} "
        f"must equal cme_minutes_pool_total {total}"
    )


def assert_quarter_credit_step(credits) -> None:
    """Credits are whole quarter credits."""
    value = round(float(credits) * 100)
    assert value % 25 == 0, f"awarded credits {credits} must be a multiple of 0.25"


def assert_two_decimal_places(value) -> None:
    """Scores are carried to two decimal places."""
    assert value is not None, "expected a numeric score, got null"
    assert round(float(value), 2) == float(value), (
        f"{value} must be expressed with at most two decimal places"
    )


def assert_four_decimal_places(value) -> None:
    """Expertise match scores are carried to four decimal places."""
    assert value is not None, "expected a numeric match score, got null"
    assert round(float(value), 4) == float(value), (
        f"{value} must be expressed with at most four decimal places"
    )
