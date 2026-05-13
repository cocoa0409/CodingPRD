"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- ProjectManager carries an OPAQUE X-User-ID. 'When X-User-Role is
  ProjectManager, X-User-ID is an opaque operator identifier not tied to
  any persisted entity. The server may record it (for example, as
  actor_id on AuditEntry rows that record state transitions performed
  by a project manager) but does not compare it against any entity's id.'
  Shared constants are safe for this role.

- Translator is ENTITY-BACKED. 'When X-User-Role is Translator, X-User-ID
  is the id of the acting Translator record; ownership checks on any
  resource that references a Translator compare the resource's foreign-key
  field (such as Assignment.translator_id or QualityScore.translator_id)
  to X-User-ID.' Every ownership-gated Translator-role call MUST use
  make_translator_headers(translator['id']) — passing a shared fallback
  constant guarantees the ownership check fails for any real translator
  id, cascading 'Setup failed' into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Translator fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — canonical constants.
    "project_manager_headers": build_user_headers(
        "project-manager-001", "ProjectManager",
    ),
    "project_manager_headers_alt": build_user_headers(
        "project-manager-002", "ProjectManager",
    ),
    # Translator fallback — use ONLY for tests that do not exercise
    # ownership. Per PRD §2.1 the real X-User-ID must equal the acting
    # Translator's id for any ownership-gated call; the per-instance
    # builder below is the correct path in fixtures and test_suite.
    "translator_headers": build_user_headers(
        "translator-fallback", "Translator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed Translator role.
# ---------------------------------------------------------------------------
def make_translator_headers(translator_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Translator, X-User-ID is the id of
    the acting Translator record.' Pass the actual Translator.id returned
    by POST /translators whenever the downstream call is ownership-gated
    (accept/reject assignment, submit-translation, submit-review,
    final-approve, reject segment, finalize quality score)."""
    return build_user_headers(translator_id, "Translator")


def make_project_manager_headers(
    user_id: str = "project-manager-001",
) -> Dict[str, str]:
    """PRD §2.1: ProjectManager X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "ProjectManager")


__all__ = [
    "TEST_USERS",
    "make_translator_headers",
    "make_project_manager_headers",
]
