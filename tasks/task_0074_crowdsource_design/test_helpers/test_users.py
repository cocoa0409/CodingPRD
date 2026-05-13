"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformOps carries an OPAQUE X-User-ID.
  "When X-User-Role is PlatformOps, X-User-ID is an opaque operator
  identifier not tied to any persisted entity."
  Shared constants are canonical for this role.

- Client, Designer, and Reviewer are ENTITY-BACKED.
  "When X-User-Role is Client, X-User-ID is the id of the acting Client;
  ownership checks on any resource that references a Client compare the
  resource's client_id to X-User-ID."
  "When X-User-Role is Designer, X-User-ID is the id of the acting
  Designer; ownership checks ... compare the resource's designer_id to
  X-User-ID."
  "When X-User-Role is Reviewer, X-User-ID is the reviewer_id of the
  acting member of the reviewer pool; assignment-ownership checks
  compare the ReviewAssignment.reviewer_id to X-User-ID."

  Every ownership-gated call by these roles MUST use the per-instance
  builder (make_client_headers / make_designer_headers /
  make_reviewer_headers) with the actual entity id. Passing a shared
  fallback string guarantees the ownership check fails against any real
  entity and cascades 'Setup failed' into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and non-binding fallbacks for entity-backed
# roles (used only for tests that do not exercise ownership: 401/403/404
# negative tests where the call is rejected before any ownership compare).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — canonical constants.
    "platform_ops_headers": build_user_headers(
        "platform-ops-001", "PlatformOps",
    ),
    "platform_ops_headers_alt": build_user_headers(
        "platform-ops-002", "PlatformOps",
    ),
    # Entity-backed fallbacks (NOT for ownership-gated calls).
    "client_headers": build_user_headers(
        "client-fallback", "Client",
    ),
    "designer_headers": build_user_headers(
        "designer-fallback", "Designer",
    ),
    "reviewer_headers": build_user_headers(
        "reviewer-fallback", "Reviewer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for every entity_backed role on any
# ownership-gated call.
# ---------------------------------------------------------------------------
def make_platform_ops_headers(user_id: str = "platform-ops-001") -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is PlatformOps, X-User-ID is an opaque
    operator identifier not tied to any persisted entity.'"""
    return build_user_headers(user_id, "PlatformOps")


def make_client_headers(client_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Client, X-User-ID is the id of the
    acting Client.' Pass the actual Client.id returned by POST /clients."""
    return build_user_headers(client_id, "Client")


def make_designer_headers(designer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Designer, X-User-ID is the id of
    the acting Designer.' Pass the actual Designer.id returned by
    POST /designers."""
    return build_user_headers(designer_id, "Designer")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Reviewer, X-User-ID is the
    reviewer_id of the acting member of the reviewer pool.' Pass the
    reviewer_id supplied to POST /reviewer-pool (the opaque external
    identifier, NOT the ReviewerPool row's id)."""
    return build_user_headers(reviewer_id, "Reviewer")


__all__ = [
    "TEST_USERS",
    "make_platform_ops_headers",
    "make_client_headers",
    "make_designer_headers",
    "make_reviewer_headers",
]
