"""Per-entity assertions for the Drug Trial Ethics API.

PRD §2.4 splits entities into two field-shapes:
- Versioned (id + created_at + updated_at + version): Application,
  Submission, CommitteeMember, Meeting, AgendaItem, Resolution,
  Rectification, AnnualReport.
- Append-only (id + created_at only; no updated_at, no version):
  ConflictDeclaration, AttendanceConfirmation, Vote, AuditLog.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 append-only shape: id + created_at ONLY."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Allowed enum sets (mirroring PRD prose)
# ---------------------------------------------------------------------------
APPLICATION_STATES = {
    "DRAFT", "PENDING_PRESCREEN", "REWORK_REQUIRED", "PENDING_REVIEW",
    "IN_REVIEW", "APPROVED", "APPROVED_WITH_MOD", "REJECTED", "DEFERRED",
    "SUSPENDED", "TERMINATED", "COMPLETED",
}
APPLICATION_PHASES = {"PHASE_I", "PHASE_II", "PHASE_III", "PHASE_IV"}
REVIEW_TRACKS = {"STANDARD", "EXPEDITED"}
PRESCREEN_STATUSES = {"PENDING", "PASSED", "REJECTED"}
MEMBER_QUALIFICATIONS = {
    "MEDICAL_EXPERT", "PHARMACOLOGIST", "ETHICIST", "LEGAL_EXPERT",
    "LAY_REPRESENTATIVE", "STATISTICIAN",
}
MEMBER_STATES = {"ACTIVE", "RESIGNED", "REMOVED"}
CONFLICT_TYPES = {"SPONSOR_RELATION", "CO_AUTHOR", "ECONOMIC_INTEREST"}
MEETING_TYPES = {"STANDARD", "EXPEDITED"}
MEETING_STATES = {
    "SCHEDULED", "AGENDA_PUBLISHED", "IN_SESSION", "CLOSED", "CANCELLED",
}
REVIEW_KINDS = {
    "INITIAL_REVIEW", "SECONDARY_REVIEW", "ANNUAL_REVIEW",
    "AMENDMENT_REVIEW", "FINAL_REPORT_REVIEW",
}
AGENDA_ITEM_STATES = {
    "DRAFT", "PUBLISHED", "OPEN_FOR_VOTING",
    "CLOSED_WITHOUT_QUORUM", "RESOLVED",
}
VOTE_MODES = {"APPROVE", "APPROVE_WITH_MODIFICATION", "REJECT", "DEFER"}
RESOLUTION_OUTCOMES = {
    "APPROVE", "APPROVE_WITH_MODIFICATION", "REJECT", "DEFER", "NO_QUORUM",
}
RECTIFICATION_STATES = {
    "OPEN", "RESPONDED", "UNDER_SECONDARY_REVIEW",
    "CLOSED_APPROVED", "CLOSED_REJECTED", "EXPIRED",
}
ANNUAL_REPORT_KINDS = {
    "ANNUAL_PROGRESS", "PROTOCOL_AMENDMENT", "FINAL_REPORT",
}
ANNUAL_REPORT_STATES = {"SUBMITTED", "SCHEDULED_FOR_REVIEW", "RESOLVED"}
ANNUAL_REPORT_OUTCOMES = {"CONTINUE", "SUSPEND", "TERMINATE"}
AUDIT_EVENT_TYPES = {
    "REVIEW_DECISION", "MEMBER_RECUSAL",
    "REGULATORY_SYNC", "IM_NOTIFICATION",
}


# ===========================================================================
# Versioned entities
# ===========================================================================
def assert_application(data: Dict[str, Any]) -> None:
    """PRD §3.1 Application fields."""
    _check_versioned_fields(data, "Application")
    assert isinstance(data.get("sponsor_name"), str) \
        and 1 <= len(data["sponsor_name"]) <= 200, (
        f"Application.sponsor_name must be 1..200 chars; got "
        f"{data.get('sponsor_name')!r}"
    )
    assert isinstance(data.get("drug_name"), str) \
        and 1 <= len(data["drug_name"]) <= 200
    assert isinstance(data.get("indication"), str) \
        and 1 <= len(data["indication"]) <= 500
    assert data.get("phase") in APPLICATION_PHASES, (
        f"Application.phase must be one of {APPLICATION_PHASES}; got "
        f"{data.get('phase')!r}"
    )
    assert data.get("review_track") in REVIEW_TRACKS, (
        f"Application.review_track must be one of {REVIEW_TRACKS}; got "
        f"{data.get('review_track')!r}"
    )
    assert data.get("status") in APPLICATION_STATES, (
        f"Application.status must be one of {APPLICATION_STATES}; got "
        f"{data.get('status')!r}"
    )
    assert isinstance(data.get("applicant_id"), str), (
        "Application.applicant_id must be string"
    )
    assert "current_submission_version" in data
    assert isinstance(data["current_submission_version"], int) \
        and data["current_submission_version"] >= 0


def assert_submission(data: Dict[str, Any]) -> None:
    """PRD §3.1 Submission fields."""
    _check_versioned_fields(data, "Submission")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("version_number"), int) \
        and data["version_number"] >= 1, (
        f"Submission.version_number must be >= 1; got "
        f"{data.get('version_number')!r}"
    )
    assert isinstance(data.get("checklist_complete"), bool)
    assert data.get("prescreen_status") in PRESCREEN_STATUSES
    assert isinstance(data.get("is_current"), bool)


def assert_committee_member(data: Dict[str, Any]) -> None:
    """PRD §3.2 CommitteeMember fields."""
    _check_versioned_fields(data, "CommitteeMember")
    assert isinstance(data.get("full_name"), str) \
        and len(data["full_name"]) >= 1
    assert data.get("qualification") in MEMBER_QUALIFICATIONS
    assert is_iso8601_timestamp(data.get("term_start", ""))
    assert is_iso8601_timestamp(data.get("term_end", ""))
    assert data.get("status") in MEMBER_STATES
    assert isinstance(data.get("is_active"), bool)
    if "affiliated_sponsors" in data and data["affiliated_sponsors"] is not None:
        assert isinstance(data["affiliated_sponsors"], list)
        for s in data["affiliated_sponsors"]:
            assert isinstance(s, str)


def assert_meeting(data: Dict[str, Any]) -> None:
    """PRD §3.3 Meeting fields."""
    _check_versioned_fields(data, "Meeting")
    assert data.get("meeting_type") in MEETING_TYPES
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data.get("status") in MEETING_STATES
    assert isinstance(data.get("convener_member_id"), str)
    assert isinstance(data.get("lead_time_hours"), int)


def assert_agenda_item(data: Dict[str, Any]) -> None:
    """PRD §3.3 AgendaItem fields."""
    _check_versioned_fields(data, "AgendaItem")
    assert isinstance(data.get("meeting_id"), str)
    assert isinstance(data.get("application_id"), str)
    assert data.get("review_kind") in REVIEW_KINDS
    assert data.get("status") in AGENDA_ITEM_STATES


def assert_resolution(data: Dict[str, Any]) -> None:
    """PRD §3.5 Resolution fields."""
    _check_versioned_fields(data, "Resolution")
    assert isinstance(data.get("agenda_item_id"), str)
    assert isinstance(data.get("application_id"), str)
    assert data.get("outcome") in RESOLUTION_OUTCOMES, (
        f"Resolution.outcome must be one of {RESOLUTION_OUTCOMES}; got "
        f"{data.get('outcome')!r}"
    )
    assert isinstance(data.get("tally"), dict), (
        f"Resolution.tally must be an object; got {type(data.get('tally'))}"
    )
    document_uri = data.get("document_uri")
    assert isinstance(document_uri, str) and document_uri, (
        f"Resolution.document_uri required; got {document_uri!r}"
    )
    # PRD §3.5: 'literal ethics-resolutions URI template formed by joining
    # the resolution's id between a leading "/ethics/resolutions/" segment
    # and a trailing "/document.pdf" suffix.'
    expected = f"/ethics/resolutions/{data['id']}/document.pdf"
    assert document_uri == expected, (
        f"Resolution.document_uri must be {expected!r}; got {document_uri!r}"
    )


def assert_rectification(data: Dict[str, Any]) -> None:
    """PRD §3.6 Rectification fields."""
    _check_versioned_fields(data, "Rectification")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("source_resolution_id"), str)
    assert data.get("status") in RECTIFICATION_STATES
    assert isinstance(data.get("opinions"), list)
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_annual_report(data: Dict[str, Any]) -> None:
    """PRD §3.7 AnnualReport fields."""
    _check_versioned_fields(data, "AnnualReport")
    assert isinstance(data.get("application_id"), str)
    assert is_iso8601_timestamp(data.get("report_period_start", ""))
    assert is_iso8601_timestamp(data.get("report_period_end", ""))
    assert data.get("report_kind") in ANNUAL_REPORT_KINDS
    assert isinstance(data.get("serious_adverse_event_count"), int) \
        and data["serious_adverse_event_count"] >= 0
    assert isinstance(data.get("total_adverse_event_count"), int) \
        and data["total_adverse_event_count"] >= 0
    assert isinstance(data.get("enrollment_count"), int) \
        and data["enrollment_count"] >= 0
    assert isinstance(data.get("safety_alert_flag"), bool)
    assert data.get("status") in ANNUAL_REPORT_STATES
    if data.get("outcome") is not None:
        assert data["outcome"] in ANNUAL_REPORT_OUTCOMES


# ===========================================================================
# Append-only entities (PRD §2.4)
# ===========================================================================
def assert_conflict_declaration(data: Dict[str, Any]) -> None:
    """PRD §3.2 ConflictDeclaration fields."""
    _check_append_only_fields(data, "ConflictDeclaration")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("application_id"), str)
    assert data.get("conflict_type") in CONFLICT_TYPES
    assert isinstance(data.get("details"), str)
    assert isinstance(data.get("auto_detected"), bool)


def assert_attendance_confirmation(data: Dict[str, Any]) -> None:
    """PRD §3.4 AttendanceConfirmation fields."""
    _check_append_only_fields(data, "AttendanceConfirmation")
    assert isinstance(data.get("agenda_item_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert is_iso8601_timestamp(data.get("confirmed_at", ""))


def assert_vote(data: Dict[str, Any]) -> None:
    """PRD §3.4 Vote fields."""
    _check_append_only_fields(data, "Vote")
    assert isinstance(data.get("agenda_item_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert data.get("vote_mode") in VOTE_MODES


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.4, §2.11 AuditLog fields."""
    _check_append_only_fields(data, "AuditLog")
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert data.get("event_type") in AUDIT_EVENT_TYPES
    assert isinstance(data.get("subject_entity"), str)
    assert isinstance(data.get("subject_id"), str)


# ===========================================================================
# Tally helpers
# ===========================================================================
def assert_tally_shape(tally: Dict[str, Any]) -> None:
    """PRD §3.5: tally records per-mode counts plus total_votes_cast,
    eligible_voter_count, quorum_required."""
    for k in ("APPROVE", "APPROVE_WITH_MODIFICATION", "REJECT", "DEFER",
              "total_votes_cast", "eligible_voter_count",
              "quorum_required"):
        assert k in tally, f"Resolution.tally missing {k!r}; got {tally!r}"
        assert isinstance(tally[k], int), (
            f"Resolution.tally.{k} must be integer"
        )
    assert tally["APPROVE"] >= 0
    assert tally["APPROVE_WITH_MODIFICATION"] >= 0
    assert tally["REJECT"] >= 0
    assert tally["DEFER"] >= 0
    assert tally["total_votes_cast"] >= 0


def assert_tally_conservation(tally: Dict[str, Any]) -> None:
    """PRD §3.5: 'the full tally object recording per-mode counts plus
    total_votes_cast, eligible_voter_count, and quorum_required'.
    PRD §2.9: 'All quorum and vote tallies are integer-valued; there is
    no rounding inside the tally itself.' Per-mode counts must sum to
    total_votes_cast."""
    s = (tally["APPROVE"]
         + tally["APPROVE_WITH_MODIFICATION"]
         + tally["REJECT"]
         + tally["DEFER"])
    assert s == tally["total_votes_cast"], (
        f"Tally bucket sum {s} != total_votes_cast "
        f"{tally['total_votes_cast']}; tally={tally!r}"
    )
    assert tally["total_votes_cast"] <= tally["eligible_voter_count"], (
        f"total_votes_cast {tally['total_votes_cast']} must not exceed "
        f"eligible_voter_count {tally['eligible_voter_count']}"
    )


# ===========================================================================
# Audit-log filtering helpers
# ===========================================================================
def find_audit_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    event_type: Optional[str] = None,
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter an iterable of AuditLog rows by event_type / subject_entity
    / subject_id (any subset)."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if event_type is not None and e.get("event_type") != event_type:
            continue
        if subject_entity is not None \
                and e.get("subject_entity") != subject_entity:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        out.append(e)
    return out


__all__ = [
    "APPLICATION_STATES", "APPLICATION_PHASES", "REVIEW_TRACKS",
    "PRESCREEN_STATUSES", "MEMBER_QUALIFICATIONS", "MEMBER_STATES",
    "CONFLICT_TYPES", "MEETING_TYPES", "MEETING_STATES",
    "REVIEW_KINDS", "AGENDA_ITEM_STATES",
    "VOTE_MODES", "RESOLUTION_OUTCOMES",
    "RECTIFICATION_STATES",
    "ANNUAL_REPORT_KINDS", "ANNUAL_REPORT_STATES", "ANNUAL_REPORT_OUTCOMES",
    "AUDIT_EVENT_TYPES",
    "assert_application", "assert_submission", "assert_committee_member",
    "assert_meeting", "assert_agenda_item", "assert_resolution",
    "assert_rectification", "assert_annual_report",
    "assert_conflict_declaration", "assert_attendance_confirmation",
    "assert_vote", "assert_audit_log",
    "assert_tally_shape", "assert_tally_conservation",
    "find_audit_entries",
]
