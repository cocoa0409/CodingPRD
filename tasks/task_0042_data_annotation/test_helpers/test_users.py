"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes two role identity shapes:

- ProjectManager and QAReviewer carry an opaque operator id in
  X-User-ID. PRD §2.1: 'X-User-ID is an opaque operator identifier not
  tied to any persisted entity. The server may record it in audit-log
  rows but does not compare it to any entity's id.' The shared
  TEST_USERS constant is canonical for these roles.

- Annotator is entity-backed. PRD §2.1: 'When X-User-Role is Annotator,
  X-User-ID is the id of the acting AnnotatorProfile; ownership checks
  on any resource that references an AnnotatorProfile (for example, the
  assigned_annotator_id of a TaskPackage, the annotator_id on an Appeal,
  or the arbiter_id on an Appeal) compare the resource's foreign-key
  field to X-User-ID.' Ownership-gated calls (claim, submit,
  rework-claim, arbitrate, /appeals, /appeals/{id}/decide) MUST use
  make_annotator_headers(annotator_id) with the actual AnnotatorProfile.id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Canonical for opaque roles; fallback for the
# entity-backed Annotator role on tests that do NOT exercise ownership
# (e.g., RBAC ERR_INSUFFICIENT_PERMISSIONS, ERR_ANNOTATOR_NOT_FOUND).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles -- canonical shared constants.
    "project_manager_headers": build_user_headers(
        "pm-001", "ProjectManager"
    ),
    "project_manager_headers_alt": build_user_headers(
        "pm-002", "ProjectManager"
    ),
    "qa_reviewer_headers": build_user_headers(
        "qa-001", "QAReviewer"
    ),
    "qa_reviewer_headers_alt": build_user_headers(
        "qa-002", "QAReviewer"
    ),

    # Fallback constant for Annotator -- used only when the call under
    # test does NOT exercise an ownership comparison.
    "annotator_headers": build_user_headers(
        "annotator-fallback", "Annotator"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed Annotator role.
# Use this whenever the call is ownership-gated -- claim, submit,
# rework-claim, arbitrate, appeal create, appeal decide.
# ---------------------------------------------------------------------------
def make_annotator_headers(annotator_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Annotator, X-User-ID is the id of
    the acting AnnotatorProfile.' Pass the actual AnnotatorProfile.id
    minted by POST /annotators."""
    return build_user_headers(annotator_id, "Annotator")


def make_project_manager_headers(
    pm_id: str = "pm-001",
) -> Dict[str, str]:
    """PRD §2.1: ProjectManager X-User-ID is an opaque operator id."""
    return build_user_headers(pm_id, "ProjectManager")


def make_qa_reviewer_headers(
    qa_id: str = "qa-001",
) -> Dict[str, str]:
    """PRD §2.1: QAReviewer X-User-ID is an opaque operator id."""
    return build_user_headers(qa_id, "QAReviewer")


__all__ = [
    "TEST_USERS",
    "make_annotator_headers",
    "make_project_manager_headers",
    "make_qa_reviewer_headers",
]
