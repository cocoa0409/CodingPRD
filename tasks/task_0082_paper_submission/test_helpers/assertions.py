"""Entity assertions for the Paper Submission API.

Uses the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
under the hood. Each asserter accepts the dict shape returned by the
respective endpoint and verifies the PRD-required fields and value
constraints.

PRD §2.4: most entities carry id + created_at + updated_at + version;
PlagiarismCheck and AuditLog are append-only (id + created_at only).
"""
from __future__ import annotations
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common envelope helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'id (a server-minted UUID with no type prefix),
    created_at and updated_at (ISO 8601 UTC timestamps with three
    fractional digits), and version (an integer that starts at 1 ...
    and is incremented by one on every mutation).'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'PlagiarismCheck and AuditLog ... carry id and created_at
    only, and neither updated_at nor version is present on them.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Author (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_author(data: dict) -> None:
    _assert_common_mutable(data, "Author")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("institution"), str)
    # PRD §3.1: 'A freshly registered author always has orcid_verified set
    # to false.' Implementation must always return this boolean field.
    assert isinstance(data.get("orcid_verified"), bool), (
        "Author.orcid_verified must be a boolean"
    )
    # orcid_id is optional but, when present, must be a string.
    if data.get("orcid_id") is not None:
        assert isinstance(data["orcid_id"], str)
    # recent_collaborator_ids default is empty list (PRD §3.1 wording).
    assert isinstance(data.get("recent_collaborator_ids", []), list)


# ---------------------------------------------------------------------------
# Reviewer (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_reviewer(data: dict) -> None:
    _assert_common_mutable(data, "Reviewer")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("institution"), str)
    assert isinstance(data.get("expertise_tags"), list)
    assert all(isinstance(t, str) for t in data["expertise_tags"])
    assert isinstance(data.get("active_assignments"), int)
    assert data["active_assignments"] >= 0
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# Editor (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_editor(data: dict) -> None:
    _assert_common_mutable(data, "Editor")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("institution"), str)
    assert data.get("role") in {
        "EDITOR_IN_CHIEF", "SECTION_EDITOR", "ASSOCIATE_EDITOR",
    }


# ---------------------------------------------------------------------------
# Manuscript (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_manuscript(data: dict) -> None:
    _assert_common_mutable(data, "Manuscript")
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert is_valid_uuid(data.get("corresponding_author_id", ""))
    assert isinstance(data.get("co_author_ids", []), list)
    assert isinstance(data.get("topic_tag"), str)
    assert data.get("review_mode") in {"SINGLE_BLIND", "DOUBLE_BLIND", "OPEN"}
    assert isinstance(data.get("manuscript_file_uri"), str)
    assert data.get("status") in {
        "DRAFT", "AWAITING_COAUTHOR", "SUBMITTED", "DESK_REJECTED",
        "UNDER_REVIEW", "REVISION_REQUIRED", "REVISION_SUBMITTED",
        "ACCEPTED", "REJECTED", "WITHDRAWN", "IN_PRODUCTION",
        "PUBLISHED", "RETRACTED",
    }
    # PRD §3.2: 'revision_round ... starts at 0.'
    assert isinstance(data.get("revision_round"), int)
    assert data["revision_round"] >= 0


# ---------------------------------------------------------------------------
# CoAuthorConfirmation (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_coauthor_confirmation(data: dict) -> None:
    _assert_common_mutable(data, "CoAuthorConfirmation")
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert is_valid_uuid(data.get("author_id", ""))
    assert data.get("status") in {"PENDING", "CONFIRMED", "DECLINED"}


# ---------------------------------------------------------------------------
# PlagiarismCheck (PRD §3.3, §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_plagiarism_check(data: dict) -> None:
    _assert_common_appendonly(data, "PlagiarismCheck")
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert isinstance(data.get("revision_round"), int)
    assert isinstance(data.get("similarity_percent"), (int, float))
    assert 0 <= data["similarity_percent"] <= 100
    assert data.get("result") in {"PASS", "FAIL"}


# ---------------------------------------------------------------------------
# ReviewerInvitation (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_reviewer_invitation(data: dict) -> None:
    _assert_common_mutable(data, "ReviewerInvitation")
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))
    assert isinstance(data.get("revision_round"), int)
    assert is_iso8601_timestamp(data.get("response_deadline_at", ""))
    assert data.get("status") in {
        "PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN",
    }
    # PRD §2.9: coi_score and match_score are integers in [0, 100].
    assert isinstance(data.get("coi_score"), int)
    assert 0 <= data["coi_score"] <= 100, (
        "ReviewerInvitation.coi_score must lie in [0, 100] "
        "(PRD §2.9)"
    )
    assert isinstance(data.get("match_score"), int)
    assert 0 <= data["match_score"] <= 100, (
        "ReviewerInvitation.match_score must lie in [0, 100] "
        "(PRD §2.9)"
    )


# ---------------------------------------------------------------------------
# Review (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_review(data: dict) -> None:
    _assert_common_mutable(data, "Review")
    assert is_valid_uuid(data.get("invitation_id", ""))
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert data.get("status") in {"DRAFT", "SUBMITTED", "SUPERSEDED"}
    if data.get("rating") is not None:
        assert isinstance(data["rating"], int)
        assert 1 <= data["rating"] <= 5, (
            "Review.rating must lie in [1, 5] (PRD §3.6)"
        )
    if data.get("recommendation") is not None:
        assert data["recommendation"] in {
            "ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT",
        }


# ---------------------------------------------------------------------------
# EditorDecision (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_editor_decision(data: dict) -> None:
    _assert_common_mutable(data, "EditorDecision")
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert isinstance(data.get("revision_round"), int)
    assert data.get("recommendation_from_associate") in {
        "ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT", "TRANSFER",
    }
    assert data.get("status") in {"DRAFT", "RECOMMENDED", "FINALIZED"}


# ---------------------------------------------------------------------------
# Publication (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_publication(data: dict) -> None:
    _assert_common_mutable(data, "Publication")
    assert is_valid_uuid(data.get("manuscript_id", ""))
    assert data.get("status") in {
        "COPY_EDITING", "PROOF_REVIEW", "ONLINE_FIRST", "PUBLISHED", "RETRACTED",
    }
    assert isinstance(data.get("indexing_status", {}), dict)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.10 — append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: dict) -> None:
    _assert_common_appendonly(data, "AuditLog")
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("entity"), str)
    assert isinstance(data.get("entity_id"), str)
    assert isinstance(data.get("action"), str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_coi_score_in_range(score: int) -> None:
    """PRD §2.9: 'coi_score ... [is] integer in the closed interval from
    0 to 100 — the result of a final cap.'"""
    assert isinstance(score, int)
    assert 0 <= score <= 100, (
        f"coi_score must be in [0, 100]; got {score}"
    )


def assert_match_score_in_range(score: int) -> None:
    """PRD §2.9 / §3.5: 'match_score clamps the raw value into the closed
    interval from 0 to 100.'"""
    assert isinstance(score, int)
    assert 0 <= score <= 100, (
        f"match_score must be in [0, 100]; got {score}"
    )


def assert_aggregate_score_two_decimals(score: float) -> None:
    """PRD §2.9 / §3.7: 'aggregate_score ... is computed to two decimal
    places using round-half-up at every rounding step.'"""
    assert isinstance(score, (int, float))
    rounded = round(float(score) * 100) / 100
    assert abs(float(score) - rounded) < 1e-9, (
        f"aggregate_score must carry two decimal places; got {score}"
    )


def find_audit(entries: list, action: str,
               entity_id: Optional[str] = None) -> Optional[dict]:
    """Return the latest AuditLog entry whose action matches (and optional
    entity_id matches), or None."""
    for entry in reversed(entries):
        if entry.get("action") != action:
            continue
        if entity_id is not None and entry.get("entity_id") != entity_id:
            continue
        return entry
    return None


__all__ = [
    "assert_author",
    "assert_reviewer",
    "assert_editor",
    "assert_manuscript",
    "assert_coauthor_confirmation",
    "assert_plagiarism_check",
    "assert_reviewer_invitation",
    "assert_review",
    "assert_editor_decision",
    "assert_publication",
    "assert_audit_log",
    "assert_coi_score_in_range",
    "assert_match_score_in_range",
    "assert_aggregate_score_two_decimals",
    "find_audit",
]
