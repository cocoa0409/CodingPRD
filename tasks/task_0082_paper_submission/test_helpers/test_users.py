"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules (paraphrased here only):

- PlatformAdmin is OPAQUE. Its X-User-ID is "an opaque operator
  identifier not tied to any persisted entity; the server may record
  it ... but does not compare it to any entity's id". Shared constants
  are canonical.

- Author, EditorInChief, SectionEditor, AssociateEditor, Reviewer are
  ENTITY-BACKED:
    - Author: X-User-ID equals Author.id; ownership checks compare it
      to Manuscript.corresponding_author_id, CoAuthorConfirmation.author_id,
      and Publication author-approval paths.
    - EditorInChief / SectionEditor / AssociateEditor: X-User-ID equals
      the Editor.id; ownership checks compare it to
      Manuscript.section_editor_id or Manuscript.associate_editor_id.
    - Reviewer: X-User-ID equals Reviewer.id; ownership checks compare it
      to ReviewerInvitation.reviewer_id (and the Review it spawned).

For entity-backed roles, fixtures MUST mint per-instance headers using
the make_<role>_headers(entity_id) builders below. Using the shared
fallback constants for an ownership-gated call guarantees the ownership
check fails for every real entity and cascades 'Setup failed' into
every downstream test.

Shared constants are exposed for tests that DO NOT exercise ownership:
authentication-missing, role-forbidden, and not-found probes.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — canonical only for the opaque PlatformAdmin role.
# Entity-backed entries are FALLBACKS used solely for non-ownership tests
# (e.g., missing-auth, wrong-role, missing-resource probes).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin (opaque) — shared constant is canonical (PRD §2.1).
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),

    # Entity-backed fallbacks — must NOT be used for ownership-gated calls.
    "author_headers": build_user_headers(
        "author-fallback", "Author",
    ),
    "editor_in_chief_headers": build_user_headers(
        "editor-in-chief-fallback", "EditorInChief",
    ),
    "section_editor_headers": build_user_headers(
        "section-editor-fallback", "SectionEditor",
    ),
    "associate_editor_headers": build_user_headers(
        "associate-editor-fallback", "AssociateEditor",
    ),
    "reviewer_headers": build_user_headers(
        "reviewer-fallback", "Reviewer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for every entity_backed role.
# Fixtures call these with the actual entity id returned from POST /authors,
# POST /editors, POST /reviewers.
# ---------------------------------------------------------------------------
def make_author_headers(author_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Author, X-User-ID is the id of the
    acting Author; ownership checks on any resource referencing an Author
    ... compare that foreign-key field to X-User-ID.'
    Pass the Author.id returned by POST /authors for every ownership-gated
    call: submit/withdraw/revise a manuscript, confirm/decline a
    co-author confirmation, approve a proof.
    """
    return build_user_headers(author_id, "Author")


def make_editor_in_chief_headers(editor_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is EditorInChief ... X-User-ID is the
    id of the acting Editor row.' Use the Editor.id whose role is
    EDITOR_IN_CHIEF for assign-section-editor, finalize, retract.
    """
    return build_user_headers(editor_id, "EditorInChief")


def make_section_editor_headers(editor_id: str) -> Dict[str, str]:
    """PRD §2.1: SectionEditor X-User-ID equals the acting Editor.id;
    ownership checks compare Manuscript.section_editor_id to it. Use the
    Editor.id with role=SECTION_EDITOR for desk-reject and assign-associate.
    """
    return build_user_headers(editor_id, "SectionEditor")


def make_associate_editor_headers(editor_id: str) -> Dict[str, str]:
    """PRD §2.1: AssociateEditor X-User-ID equals the acting Editor.id;
    ownership checks compare Manuscript.associate_editor_id to it. Use
    the Editor.id with role=ASSOCIATE_EDITOR for invitation create,
    invitation withdraw, decision create/recommend, reinvite-reviewers.
    """
    return build_user_headers(editor_id, "AssociateEditor")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Reviewer, X-User-ID is the id of
    the acting Reviewer; the reviewer_id on a ReviewerInvitation ... must
    equal X-User-ID for the reviewer-facing transitions.' Use the
    Reviewer.id returned by POST /reviewers for accept/decline/patch/submit.
    """
    return build_user_headers(reviewer_id, "Reviewer")


__all__ = [
    "TEST_USERS",
    "make_author_headers",
    "make_editor_in_chief_headers",
    "make_section_editor_headers",
    "make_associate_editor_headers",
    "make_reviewer_headers",
]
