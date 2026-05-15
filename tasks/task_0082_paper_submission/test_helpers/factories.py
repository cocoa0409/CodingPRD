"""Payload factories — one per endpoint that takes a body.

Only fields from PRD §3 / §4 input columns. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the whole payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def _unique_email(prefix: str = "person") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _unique_orcid() -> str:
    """A 16-digit ORCID matching ^\\d{4}-\\d{4}-\\d{4}-\\d{4}$ (PRD §3.1).
    We synthesize from the hex of a random UUID, zero-padded if needed.
    """
    hex_str = uuid.uuid4().hex  # 32 hex chars, contains digits + letters.
    digits = "".join(c for c in hex_str if c.isdigit())
    # Ensure we have at least 16 digits; pad with deterministic noise.
    while len(digits) < 16:
        digits += "0123456789"
    digits = digits[:16]
    return f"{digits[0:4]}-{digits[4:8]}-{digits[8:12]}-{digits[12:16]}"


# ---------------------------------------------------------------------------
# Author (PRD §3.1)
# Required: full_name, email, institution. Optional: orcid_id, recent_collaborator_ids.
# ---------------------------------------------------------------------------
def create_author_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Authors enter the system through registration, where
    full_name, email, and institution are required and orcid_id and
    recent_collaborator_ids are optional.'"""
    defaults: Dict[str, Any] = {
        "full_name": "Test Author",
        "email": _unique_email("author"),
        "institution": TEST_DEFAULTS["AUTHOR_INSTITUTION"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Reviewer (PRD §3.5, §4 Table)
# Required: full_name, email, institution, expertise_tags.
# ---------------------------------------------------------------------------
def create_reviewer_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5 — pool members carry expertise_tags ('lower-snake-case');
    PRD §4 input for POST /reviewers: full_name, email, institution,
    expertise_tags, recent_collaborator_ids?."""
    defaults: Dict[str, Any] = {
        "full_name": "Test Reviewer",
        "email": _unique_email("reviewer"),
        "institution": TEST_DEFAULTS["REVIEWER_INSTITUTION"],
        "expertise_tags": [TEST_DEFAULTS["TOPIC_TAG"]],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Editor (PRD §3.4, §4 Table)
# Required: full_name, email, institution, role. Optional: topic_tags (required
# for SECTION_EDITOR and ASSOCIATE_EDITOR per the entity table).
# ---------------------------------------------------------------------------
def create_editor_payload(role: str,
                          topic_tags: Optional[List[str]] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 — editors carry role ∈ {EDITOR_IN_CHIEF, SECTION_EDITOR,
    ASSOCIATE_EDITOR}; PRD §3.5 + §3.4 require topic_tags to match the
    manuscript's topic_tag for the associate-editor assignment."""
    payload: Dict[str, Any] = {
        "full_name": "Test Editor",
        "email": _unique_email("editor"),
        "institution": TEST_DEFAULTS["EDITOR_INSTITUTION"],
        "role": role,
    }
    if topic_tags is not None:
        payload["topic_tags"] = topic_tags
    elif role in ("SECTION_EDITOR", "ASSOCIATE_EDITOR"):
        payload["topic_tags"] = [TEST_DEFAULTS["TOPIC_TAG"]]
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Manuscript (PRD §3.2, §4 Table)
# Required: title, corresponding_author_id, topic_tag, review_mode,
#           manuscript_file_uri, declaration_coi, declaration_funding,
#           declaration_ethics. Optional: co_author_ids, supplementary_file_uris,
#           suggested_reviewer_ids, excluded_reviewer_ids.
# ---------------------------------------------------------------------------
def create_manuscript_payload(corresponding_author_id: str,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — DRAFT must carry title, corresponding_author_id, topic_tag,
    review_mode, manuscript_file_uri, and the three declarations
    (declaration_coi, declaration_funding, declaration_ethics)."""
    defaults: Dict[str, Any] = {
        "title": TEST_DEFAULTS["MANUSCRIPT_TITLE"],
        "corresponding_author_id": corresponding_author_id,
        "topic_tag": TEST_DEFAULTS["TOPIC_TAG"],
        "review_mode": TEST_DEFAULTS["REVIEW_MODE"],
        "manuscript_file_uri": TEST_DEFAULTS["MANUSCRIPT_FILE_URI"],
        "declaration_coi": TEST_DEFAULTS["DECLARATION_COI"],
        "declaration_funding": TEST_DEFAULTS["DECLARATION_FUNDING"],
        "declaration_ethics": TEST_DEFAULTS["DECLARATION_ETHICS"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# /assign-section-editor (PRD §3.4)
# ---------------------------------------------------------------------------
def assign_section_editor_payload(section_editor_id: str,
                                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'The editor-in-chief assigns a section editor to a
    submitted manuscript by supplying section_editor_id on the assignment
    request.'"""
    payload: Dict[str, Any] = {"section_editor_id": section_editor_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /assign-associate (PRD §3.4)
# ---------------------------------------------------------------------------
def assign_associate_payload(associate_editor_id: str,
                             **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'The section editor supplies associate_editor_id on the
    request body.'"""
    payload: Dict[str, Any] = {"associate_editor_id": associate_editor_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /desk-reject (PRD §3.4)
# ---------------------------------------------------------------------------
def desk_reject_payload(reason: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'either the latest PlagiarismCheck.result must be FAIL or
    the request body must supply a non-empty reason string.'"""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invitation create (PRD §3.5)
# ---------------------------------------------------------------------------
def create_invitation_payload(reviewer_id: str,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'The invitation request carries the candidate reviewer_id ...'"""
    payload: Dict[str, Any] = {"reviewer_id": reviewer_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Review patch (PRD §3.6)
# ---------------------------------------------------------------------------
def patch_review_payload(rating: Optional[int] = None,
                         recommendation: Optional[str] = None,
                         comments_to_author: Optional[str] = None,
                         comments_to_editor: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 — the reviewer 'edits the row through partial updates,
    setting rating, recommendation, comments_to_author, and
    comments_to_editor.' Any subset of fields may be supplied."""
    payload: Dict[str, Any] = {}
    if rating is not None:
        payload["rating"] = rating
    if recommendation is not None:
        payload["recommendation"] = recommendation
    if comments_to_author is not None:
        payload["comments_to_author"] = comments_to_author
    if comments_to_editor is not None:
        payload["comments_to_editor"] = comments_to_editor
    payload.update(overrides)
    return payload


def complete_review_patch_payload(rating: int = 4,
                                  recommendation: str = "ACCEPT",
                                  comments_to_author: str = "good paper",
                                  comments_to_editor: str = "fine",
                                  **overrides: Any) -> Dict[str, Any]:
    """All four review fields filled — convenient for tests that need a
    submittable review without crafting individual fields."""
    payload: Dict[str, Any] = {
        "rating": rating,
        "recommendation": recommendation,
        "comments_to_author": comments_to_author,
        "comments_to_editor": comments_to_editor,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Decision create (PRD §3.7)
# ---------------------------------------------------------------------------
def create_decision_payload(recommendation_from_associate: str = "ACCEPT",
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'The creation request carries recommendation_from_associate
    — one of ACCEPT, MINOR_REVISION, MAJOR_REVISION, REJECT, or TRANSFER —
    and the decision is created in DRAFT.'"""
    payload: Dict[str, Any] = {
        "recommendation_from_associate": recommendation_from_associate,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Decision finalize (PRD §3.7)
# ---------------------------------------------------------------------------
def finalize_decision_payload(final_decision: str = "ACCEPT",
                              decision_letter_body: Optional[str] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'The finalize request carries final_decision (one of
    ACCEPT, MINOR_REVISION, MAJOR_REVISION, REJECT, or TRANSFER) and a
    non-empty decision_letter_body.'"""
    payload: Dict[str, Any] = {
        "final_decision": final_decision,
        "decision_letter_body": (
            decision_letter_body
            if decision_letter_body is not None
            else TEST_DEFAULTS["DECISION_LETTER_BODY"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Revision submit (PRD §3.8)
# ---------------------------------------------------------------------------
def submit_revision_payload(response_letter: Optional[str] = None,
                            revised_file_uri: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'The author submits a revised manuscript by supplying
    response_letter and revised_file_uri on the request body.'"""
    payload: Dict[str, Any] = {
        "response_letter": (
            response_letter
            if response_letter is not None
            else TEST_DEFAULTS["RESPONSE_LETTER"]
        ),
        "revised_file_uri": (
            revised_file_uri
            if revised_file_uri is not None
            else TEST_DEFAULTS["REVISED_FILE_URI"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reinvite reviewers (PRD §3.8)
# ---------------------------------------------------------------------------
def reinvite_reviewers_payload(reviewer_ids: List[str],
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'the reinvite-reviewers action, which carries an array of
    reviewer_ids.'"""
    payload: Dict[str, Any] = {"reviewer_ids": list(reviewer_ids)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Publication create (PRD §3.9)
# ---------------------------------------------------------------------------
def create_publication_payload(copy_edit_uri: Optional[str] = None,
                               proof_uri: Optional[str] = None,
                               issue_label: Optional[str] = None,
                               indexing_targets: Optional[List[str]] = None,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'The creation request carries copy_edit_uri, proof_uri,
    issue_label, and an optional indexing_targets array drawn from the
    set {PUBMED, WEB_OF_SCIENCE, SCOPUS}.'"""
    payload: Dict[str, Any] = {
        "copy_edit_uri": (
            copy_edit_uri
            if copy_edit_uri is not None
            else TEST_DEFAULTS["COPY_EDIT_URI"]
        ),
        "proof_uri": (
            proof_uri
            if proof_uri is not None
            else TEST_DEFAULTS["PROOF_URI"]
        ),
        "issue_label": (
            issue_label
            if issue_label is not None
            else TEST_DEFAULTS["DEFAULT_ISSUE_LABEL"]
        ),
    }
    if indexing_targets is not None:
        payload["indexing_targets"] = list(indexing_targets)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Event ingestion / test-driving (PRD §4)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_iso: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §4 + §3.8: '/_clock/advance ... accepts a `to` instant and
    moves the server's notion of "now" forward to that value.'"""
    payload: Dict[str, Any] = {"to": to_iso}
    payload.update(overrides)
    return payload


def orcid_verified_event_payload(author_id: str, orcid_id: str,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'the platform receives an event carrying the author_id and
    orcid_id, and when the supplied orcid_id matches the stored value the
    system flips orcid_verified to true.'"""
    payload: Dict[str, Any] = {
        "author_id": author_id,
        "orcid_id": orcid_id,
    }
    payload.update(overrides)
    return payload


def plagiarism_result_event_payload(manuscript_id: str,
                                    similarity_percent: float,
                                    report_uri: Optional[str] = None,
                                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'The report supplies the manuscript_id, a similarity_percent
    between 0 and 100, and a report_uri ...'"""
    payload: Dict[str, Any] = {
        "manuscript_id": manuscript_id,
        "similarity_percent": similarity_percent,
        "report_uri": (
            report_uri
            if report_uri is not None
            else TEST_DEFAULTS["REPORT_URI"]
        ),
    }
    payload.update(overrides)
    return payload


def doi_mint_event_payload(publication_id: str, doi: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'on receipt of the doi-mint event with the publication_id
    and doi, writes Publication.doi.'"""
    payload: Dict[str, Any] = {
        "publication_id": publication_id,
        "doi": doi,
    }
    payload.update(overrides)
    return payload


def indexing_ack_event_payload(publication_id: str, target: str,
                               status: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'The system later records each external indexer's
    acknowledgement through an indexing-ack event carrying the
    publication_id, the target, and the status (ACK or FAILED).'"""
    payload: Dict[str, Any] = {
        "publication_id": publication_id,
        "target": target,
        "status": status,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "create_author_payload",
    "create_reviewer_payload",
    "create_editor_payload",
    "create_manuscript_payload",
    "assign_section_editor_payload",
    "assign_associate_payload",
    "desk_reject_payload",
    "create_invitation_payload",
    "patch_review_payload",
    "complete_review_patch_payload",
    "create_decision_payload",
    "finalize_decision_payload",
    "submit_revision_payload",
    "reinvite_reviewers_payload",
    "create_publication_payload",
    "clock_advance_payload",
    "orcid_verified_event_payload",
    "plagiarism_result_event_payload",
    "doi_mint_event_payload",
    "indexing_ack_event_payload",
]
