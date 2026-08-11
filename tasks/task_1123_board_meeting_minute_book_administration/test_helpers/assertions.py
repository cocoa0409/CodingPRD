"""Entity assertions and domain invariant checkers for the Board Governance API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive int, got {data.get('version')!r}"
    )


def assert_corporation(data: dict):
    _assert_common(data, "Corporation")
    assert isinstance(data.get("name"), str) and data["name"], "Corporation.name must be a non-empty string"
    assert isinstance(data.get("incorporation_state"), str), "Corporation.incorporation_state must be a string"
    assert "current_bylaws_id" in data, "Corporation.current_bylaws_id must be present (null allowed)"
    assert isinstance(data.get("active_director_count"), int), "Corporation.active_director_count must be an int"


def assert_bylaws(data: dict):
    _assert_common(data, "Bylaws")
    assert isinstance(data.get("corporation_id"), str), "Bylaws.corporation_id must be a string"
    assert isinstance(data.get("version_no"), int), "Bylaws.version_no must be an int"
    for f in (
        "notice_days_regular",
        "notice_days_special",
        "package_lead_days",
        "quorum_percent",
        "quorum_fixed_count",
        "consent_window_days",
        "minute_retention_years",
        "rotation_max_years",
        "board_seat_count",
    ):
        assert isinstance(data.get(f), int), f"Bylaws.{f} must be an int, got {data.get(f)!r}"
    assert isinstance(data.get("consent_unanimity_required"), bool), "Bylaws.consent_unanimity_required must be a bool"
    assert data.get("status") in ("DRAFT", "ADOPTED", "SUPERSEDED"), f"Bylaws.status unexpected: {data.get('status')!r}"


def assert_director(data: dict):
    _assert_common(data, "Director")
    assert isinstance(data.get("corporation_id"), str), "Director.corporation_id must be a string"
    assert isinstance(data.get("full_name"), str) and data["full_name"], "Director.full_name must be a non-empty string"
    assert isinstance(data.get("email"), str) and data["email"], "Director.email must be a non-empty string"
    assert data.get("independence_status") in ("INDEPENDENT", "NON_INDEPENDENT", "PENDING_REVIEW"), (
        f"Director.independence_status unexpected: {data.get('independence_status')!r}"
    )
    assert is_iso8601_timestamp(data.get("term_start", "")), "Director.term_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("term_end", "")), "Director.term_end must be ISO 8601"
    assert data.get("status") in ("ACTIVE", "RESIGNED", "TERM_EXPIRED"), (
        f"Director.status unexpected: {data.get('status')!r}"
    )


def assert_committee(data: dict):
    _assert_common(data, "Committee")
    assert data.get("committee_type") in ("AUDIT", "COMPENSATION", "NOMINATING", "SPECIAL"), (
        f"Committee.committee_type unexpected: {data.get('committee_type')!r}"
    )
    assert data.get("status") in ("CHARTER_DRAFT", "ACTIVE", "BELOW_QUORUM", "DISSOLVED"), (
        f"Committee.status unexpected: {data.get('status')!r}"
    )
    assert isinstance(data.get("chair_vacant"), bool), "Committee.chair_vacant must be a bool"
    assert isinstance(data.get("active_member_count"), int), "Committee.active_member_count must be an int"


def assert_committee_membership(data: dict):
    _assert_common(data, "CommitteeMembership")
    assert isinstance(data.get("committee_id"), str), "CommitteeMembership.committee_id must be a string"
    assert isinstance(data.get("director_id"), str), "CommitteeMembership.director_id must be a string"
    assert data.get("committee_role") in ("CHAIR", "MEMBER"), (
        f"CommitteeMembership.committee_role unexpected: {data.get('committee_role')!r}"
    )
    assert data.get("status") in ("ACTIVE", "ENDED"), f"CommitteeMembership.status unexpected: {data.get('status')!r}"


def assert_meeting(data: dict):
    _assert_common(data, "Meeting")
    assert isinstance(data.get("corporation_id"), str), "Meeting.corporation_id must be a string"
    assert data.get("meeting_type") in ("REGULAR", "SPECIAL", "ANNUAL"), (
        f"Meeting.meeting_type unexpected: {data.get('meeting_type')!r}"
    )
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "Meeting.scheduled_start must be ISO 8601"
    assert isinstance(data.get("duration_minutes"), int), "Meeting.duration_minutes must be an int"
    assert isinstance(data.get("chair_director_id"), str), "Meeting.chair_director_id must be a string"
    assert data.get("status") in ("SCHEDULED", "NOTICED", "IN_SESSION", "ADJOURNED", "CANCELLED"), (
        f"Meeting.status unexpected: {data.get('status')!r}"
    )


def assert_meeting_notice(data: dict):
    _assert_common(data, "MeetingNotice")
    assert isinstance(data.get("meeting_id"), str), "MeetingNotice.meeting_id must be a string"
    assert isinstance(data.get("director_id"), str), "MeetingNotice.director_id must be a string"
    assert isinstance(data.get("required_notice_days"), int), "MeetingNotice.required_notice_days must be an int"
    assert isinstance(data.get("is_timely"), bool), "MeetingNotice.is_timely must be a bool"
    assert data.get("status") in ("SENT", "WAIVED"), f"MeetingNotice.status unexpected: {data.get('status')!r}"


def assert_agenda_item(data: dict):
    _assert_common(data, "AgendaItem")
    assert isinstance(data.get("meeting_id"), str), "AgendaItem.meeting_id must be a string"
    assert isinstance(data.get("title"), str), "AgendaItem.title must be a string"
    assert isinstance(data.get("order_index"), int), "AgendaItem.order_index must be an int"
    assert data.get("status") in ("PROPOSED", "INCLUDED", "DROPPED"), (
        f"AgendaItem.status unexpected: {data.get('status')!r}"
    )


def assert_board_package(data: dict):
    _assert_common(data, "BoardPackage")
    assert isinstance(data.get("meeting_id"), str), "BoardPackage.meeting_id must be a string"
    assert isinstance(data.get("seal_count"), int), "BoardPackage.seal_count must be an int"
    assert isinstance(data.get("document_count"), int), "BoardPackage.document_count must be an int"
    assert data.get("status") in ("ASSEMBLING", "SEALED", "DISTRIBUTED", "WITHDRAWN"), (
        f"BoardPackage.status unexpected: {data.get('status')!r}"
    )


def assert_package_document(data: dict):
    _assert_common(data, "PackageDocument")
    assert isinstance(data.get("package_id"), str), "PackageDocument.package_id must be a string"
    assert isinstance(data.get("title"), str), "PackageDocument.title must be a string"
    assert data.get("confidentiality_tier") in ("GENERAL", "CONFIDENTIAL", "RESTRICTED"), (
        f"PackageDocument.confidentiality_tier unexpected: {data.get('confidentiality_tier')!r}"
    )


def assert_attendance_record(data: dict):
    _assert_common(data, "AttendanceRecord")
    assert isinstance(data.get("meeting_id"), str), "AttendanceRecord.meeting_id must be a string"
    assert isinstance(data.get("director_id"), str), "AttendanceRecord.director_id must be a string"
    assert data.get("attendance_mode") in ("IN_PERSON", "REMOTE", "PROXY", "ABSENT"), (
        f"AttendanceRecord.attendance_mode unexpected: {data.get('attendance_mode')!r}"
    )


def assert_resolution(data: dict):
    _assert_common(data, "Resolution")
    assert isinstance(data.get("corporation_id"), str), "Resolution.corporation_id must be a string"
    assert data.get("origin") in ("MEETING", "WRITTEN_CONSENT"), (
        f"Resolution.origin unexpected: {data.get('origin')!r}"
    )
    assert data.get("resolution_type") in ("ORDINARY", "SPECIAL"), (
        f"Resolution.resolution_type unexpected: {data.get('resolution_type')!r}"
    )
    assert data.get("status") in (
        "DRAFT",
        "TABLED",
        "VOTE_OPEN",
        "ADOPTED",
        "REJECTED",
        "CIRCULATING",
        "CONSENT_ADOPTED",
        "CONSENT_LAPSED",
    ), f"Resolution.status unexpected: {data.get('status')!r}"
    for f in ("for_count", "against_count", "abstain_count", "recused_count"):
        assert isinstance(data.get(f), int), f"Resolution.{f} must be an int"


def assert_vote_record(data: dict):
    _assert_common(data, "VoteRecord")
    assert isinstance(data.get("resolution_id"), str), "VoteRecord.resolution_id must be a string"
    assert isinstance(data.get("director_id"), str), "VoteRecord.director_id must be a string"
    assert data.get("channel") in ("MEETING_BALLOT", "WRITTEN_CONSENT"), (
        f"VoteRecord.channel unexpected: {data.get('channel')!r}"
    )
    assert data.get("vote") in ("FOR", "AGAINST", "ABSTAIN", "RECUSED"), (
        f"VoteRecord.vote unexpected: {data.get('vote')!r}"
    )
    assert data.get("status") in ("ACTIVE", "VOIDED"), f"VoteRecord.status unexpected: {data.get('status')!r}"
    assert isinstance(data.get("recast_count"), int), "VoteRecord.recast_count must be an int"


def assert_conflict_disclosure(data: dict):
    _assert_common(data, "ConflictDisclosure")
    assert isinstance(data.get("director_id"), str), "ConflictDisclosure.director_id must be a string"
    assert isinstance(data.get("corporation_id"), str), "ConflictDisclosure.corporation_id must be a string"
    assert isinstance(data.get("related_party"), str), "ConflictDisclosure.related_party must be a string"
    assert data.get("status") in ("OPEN", "CLEARED"), f"ConflictDisclosure.status unexpected: {data.get('status')!r}"


def assert_minutes(data: dict):
    _assert_common(data, "Minutes")
    assert isinstance(data.get("meeting_id"), str), "Minutes.meeting_id must be a string"
    assert isinstance(data.get("corporation_id"), str), "Minutes.corporation_id must be a string"
    assert isinstance(data.get("content"), str), "Minutes.content must be a string"
    assert data.get("status") in (
        "DRAFT",
        "CIRCULATED_FOR_REVIEW",
        "REJECTED",
        "APPROVED",
        "ENTERED_IN_BOOK",
        "PURGED",
    ), f"Minutes.status unexpected: {data.get('status')!r}"
    assert isinstance(data.get("review_round"), int), "Minutes.review_round must be an int"


def assert_audit_request(data: dict):
    _assert_common(data, "AuditRequest")
    assert isinstance(data.get("corporation_id"), str), "AuditRequest.corporation_id must be a string"
    assert isinstance(data.get("requested_by_label"), str), "AuditRequest.requested_by_label must be a string"
    assert data.get("status") in ("OPEN", "RECONSTRUCTING", "COMPLETED", "FAILED"), (
        f"AuditRequest.status unexpected: {data.get('status')!r}"
    )
