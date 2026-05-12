"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- ContentReviewer, LegalReviewer, FinancialReviewer, PlatformAdmin:
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity row. The shared TEST_USERS constant is canonical for these roles.

- Initiator: entity-backed on Initiator. PRD §2.1: 'When X-User-Role is
  Initiator, X-User-ID is the id of the acting Initiator; ownership checks
  on any resource that references an Initiator (for example, a project's
  initiator_id) compare that resource's foreign-key field to X-User-ID.'
  Ownership-gated calls (PATCH /projects, POST /projects/{id}/submit,
  /cancel, POST /projects/{project_id}/rewards, /add-on-items,
  /progress-updates, etc.) MUST use make_initiator_headers(initiator_id)
  with the actual Initiator.id.

- Backer: entity-backed on Backer. PRD §2.1: 'When X-User-Role is Backer,
  X-User-ID is the id of the acting Backer; ownership checks on orders and
  refund requests compare the resource's backer_id ... to X-User-ID.'
  Ownership-gated calls (POST /orders, PATCH /orders/{id}, /cancel,
  POST /refund-requests for own order) MUST use make_backer_headers(backer_id)
  with the actual Backer.id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For the four opaque roles, these are canonical. For
# Initiator and Backer (entity-backed), the constants are fallbacks for
# tests that don't exercise ownership comparison (e.g., ERR_FORBIDDEN
# wrong-role tests, ERR_NOT_FOUND on missing resource).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical shared constants.
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin"
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin"
    ),
    "content_reviewer_headers": build_user_headers(
        "content-reviewer-001", "ContentReviewer"
    ),
    "content_reviewer_headers_alt": build_user_headers(
        "content-reviewer-002", "ContentReviewer"
    ),
    "legal_reviewer_headers": build_user_headers(
        "legal-reviewer-001", "LegalReviewer"
    ),
    "legal_reviewer_headers_alt": build_user_headers(
        "legal-reviewer-002", "LegalReviewer"
    ),
    "financial_reviewer_headers": build_user_headers(
        "financial-reviewer-001", "FinancialReviewer"
    ),
    "financial_reviewer_headers_alt": build_user_headers(
        "financial-reviewer-002", "FinancialReviewer"
    ),
    # Fallback constants — only for non-ownership tests (e.g., RBAC
    # wrong-role checks). Ownership-gated tests must build per-instance
    # headers via make_initiator_headers / make_backer_headers.
    "initiator_headers": build_user_headers(
        "initiator-fallback-001", "Initiator"
    ),
    "backer_headers": build_user_headers(
        "backer-fallback-001", "Backer"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles.
# ---------------------------------------------------------------------------
def make_initiator_headers(initiator_id: str) -> Dict[str, str]:
    """Initiator headers. PRD §2.1: 'When X-User-Role is Initiator, X-User-ID
    is the id of the acting Initiator; ownership checks on any resource that
    references an Initiator (for example, a project's initiator_id) compare
    that resource's foreign-key field to X-User-ID.'

    Pass the actual Initiator.id whenever the call is ownership-gated.
    """
    return build_user_headers(initiator_id, "Initiator")


def make_backer_headers(backer_id: str) -> Dict[str, str]:
    """Backer headers. PRD §2.1: 'When X-User-Role is Backer, X-User-ID is
    the id of the acting Backer; ownership checks on orders and refund
    requests compare the resource's backer_id (directly on orders, or via
    the linked order for a refund request) to X-User-ID.'

    Pass the actual Backer.id whenever the call is ownership-gated.
    """
    return build_user_headers(backer_id, "Backer")


# ---------------------------------------------------------------------------
# Per-instance builders for opaque roles (lets a test pin a specific
# X-User-ID, e.g. for segregation-of-duties scenarios where the same actor
# id must be reused).
# ---------------------------------------------------------------------------
def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_content_reviewer_headers(
    reviewer_id: str = "content-reviewer-001",
) -> Dict[str, str]:
    return build_user_headers(reviewer_id, "ContentReviewer")


def make_legal_reviewer_headers(
    reviewer_id: str = "legal-reviewer-001",
) -> Dict[str, str]:
    return build_user_headers(reviewer_id, "LegalReviewer")


def make_financial_reviewer_headers(
    reviewer_id: str = "financial-reviewer-001",
) -> Dict[str, str]:
    return build_user_headers(reviewer_id, "FinancialReviewer")


__all__ = [
    "TEST_USERS",
    "make_initiator_headers",
    "make_backer_headers",
    "make_platform_admin_headers",
    "make_content_reviewer_headers",
    "make_legal_reviewer_headers",
    "make_financial_reviewer_headers",
]
