"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

  "For all five roles, identity is opaque: when X-User-Role is
  PlatformAdmin, DataSteward, FactorManager, Verifier, or Discloser,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity. The server records it ... but does not compare it to any
  entity's id."

Because all five roles are opaque, the shared TEST_USERS constants are
canonical for every call — there is no entity-backed ownership check
that compares X-User-ID against any entity primary key.

The single business-safety rule that compares two X-User-ID values is
segregation of duties on report verification (PRD §3.7): the verifying
user's X-User-ID must not equal the entered_by_user_id captured on any
ActivityData of the report's period. That comparison is between two
X-User-ID strings the server itself captured on different rows — never
between X-User-ID and an entity primary key. To exercise it, tests
build two headers that share the same X-User-ID under different roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — canonical for every opaque role (PRD §2.1).
# Distinct X-User-ID strings allow segregation-of-duties tests to compare
# steward vs verifier identities.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "data_steward_headers": build_user_headers(
        "data-steward-001", "DataSteward",
    ),
    "data_steward_headers_alt": build_user_headers(
        "data-steward-002", "DataSteward",
    ),
    "factor_manager_headers": build_user_headers(
        "factor-manager-001", "FactorManager",
    ),
    "factor_manager_headers_alt": build_user_headers(
        "factor-manager-002", "FactorManager",
    ),
    "verifier_headers": build_user_headers(
        "verifier-001", "Verifier",
    ),
    "verifier_headers_alt": build_user_headers(
        "verifier-002", "Verifier",
    ),
    "discloser_headers": build_user_headers(
        "discloser-001", "Discloser",
    ),
}


# ---------------------------------------------------------------------------
# Helper for segregation-of-duties tests (PRD §3.7).
# Returns a header pair where the steward and verifier share the SAME
# X-User-ID — the server should reject the verify because the verifier
# matches the entered_by_user_id of the activity data.
# ---------------------------------------------------------------------------
def make_steward_verifier_headers(user_id: str) -> Dict[str, Dict[str, str]]:
    """PRD §3.7: 'the verifying user's X-User-ID must not equal the
    entered_by_user_id of any ActivityData row whose reporting_period_id
    matches the report's reporting period.'

    Returns {"steward": ..., "verifier": ...} both carrying user_id but
    under different X-User-Role values, so the verify call collides
    with the steward's previously-captured entered_by_user_id.
    """
    return {
        "steward": build_user_headers(user_id, "DataSteward"),
        "verifier": build_user_headers(user_id, "Verifier"),
    }


__all__ = [
    "TEST_USERS",
    "make_steward_verifier_headers",
]
