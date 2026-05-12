"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 distinguishes two role identity shapes:

- DistributorOps and CinemaOps are entity-backed.

  PRD §2.1: 'When X-User-Role is DistributorOps, X-User-ID is the id of
  the acting Distributor; ownership checks on any resource that
  references a Distributor compare the resource's foreign-key field to
  X-User-ID.'

  PRD §2.1: 'When X-User-Role is CinemaOps, X-User-ID is the id of the
  acting Cinema; ownership checks on any resource that references a
  Cinema compare the resource's foreign-key field to X-User-ID.'

  Ownership-gated calls (POST /films/{id}/release by DistributorOps,
  POST /cinemas/{id}/screens by CinemaOps, POST /screens/{id}/showtimes,
  POST /showtimes/{id}/cancel, etc.) MUST use make_<role>_headers
  (entity_id) with the real entity's id. Falling back to the shared
  TEST_USERS constant for an entity-backed role would make every
  ownership check fail.

- PlatformAdmin, TicketingPlatform, FinanceOps, and Auditor are opaque.
  PRD §2.1: 'X-User-ID is an opaque operator identifier not tied to any
  persisted entity. The server may record it ... but does not compare
  it to any entity's id.' The shared TEST_USERS constant is canonical
  for these four roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared fallback constants. Canonical for opaque roles; fallback for
# entity-backed roles on tests that do NOT exercise ownership
# (e.g., RBAC ERR_ROLE_FORBIDDEN, ERR_NOT_FOUND, ERR_AUTH_HEADERS_MISSING).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles -- canonical constants.
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin",
    ),
    "ticketing_platform_headers": build_user_headers(
        "ticketing-001", "TicketingPlatform",
    ),
    "finance_ops_headers": build_user_headers(
        "finance-001", "FinanceOps",
    ),
    "auditor_headers": build_user_headers(
        "auditor-001", "Auditor",
    ),
    # Fallback constants for entity-backed roles. Use ONLY when ownership
    # is not exercised.
    "distributor_ops_headers": build_user_headers(
        "distributor-fallback", "DistributorOps",
    ),
    "cinema_ops_headers": build_user_headers(
        "cinema-fallback", "CinemaOps",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles. Use these whenever the
# call is ownership-gated so the X-User-ID resolves to a real entity id.
# ---------------------------------------------------------------------------
def make_distributor_ops_headers(distributor_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is DistributorOps, X-User-ID is the id
    of the acting Distributor; ownership checks on any resource that
    references a Distributor compare the resource's foreign-key field to
    X-User-ID.' Pass the actual Distributor.id minted by POST
    /distributors."""
    return build_user_headers(distributor_id, "DistributorOps")


def make_cinema_ops_headers(cinema_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is CinemaOps, X-User-ID is the id of
    the acting Cinema; ownership checks on any resource that references
    a Cinema compare the resource's foreign-key field to X-User-ID.'
    Pass the actual Cinema.id minted by POST /cinemas."""
    return build_user_headers(cinema_id, "CinemaOps")


def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is an opaque operator id."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_ticketing_platform_headers(
    op_id: str = "ticketing-001",
) -> Dict[str, str]:
    """PRD §2.1: TicketingPlatform X-User-ID is an opaque operator id."""
    return build_user_headers(op_id, "TicketingPlatform")


def make_finance_ops_headers(
    op_id: str = "finance-001",
) -> Dict[str, str]:
    """PRD §2.1: FinanceOps X-User-ID is an opaque operator id."""
    return build_user_headers(op_id, "FinanceOps")


def make_auditor_headers(
    op_id: str = "auditor-001",
) -> Dict[str, str]:
    """PRD §2.1: Auditor X-User-ID is an opaque operator id."""
    return build_user_headers(op_id, "Auditor")


__all__ = [
    "TEST_USERS",
    "make_distributor_ops_headers",
    "make_cinema_ops_headers",
    "make_platform_admin_headers",
    "make_ticketing_platform_headers",
    "make_finance_ops_headers",
    "make_auditor_headers",
]
