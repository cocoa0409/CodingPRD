"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin, RegistrationReviewer, FinanceOps, DisputeOfficer, and
  PlaybackSource carry OPAQUE X-User-IDs. The PRD states for each that the
  X-User-ID "is an opaque operator identifier not tied to any persisted
  entity" and the server "does not compare it to any entity's id." Shared
  constants are safe in every call.

- RightsHolder is ENTITY-BACKED. PRD §2.1:
    "When X-User-Role is RightsHolder, X-User-ID is the id of the acting
     RightsHolder; ownership checks on any resource that references a
     RightsHolder compare the resource's foreign-key field to X-User-ID.
     A holder may only submit, withdraw, share-edit, or dispute-withdraw
     on resources whose owner identifier matches their X-User-ID."

  Every ownership-gated RightsHolder-role call therefore MUST use
  make_rights_holder_headers(holder['id']) with the actual entity's id.
  Falling back to the shared constant guarantees the ownership check fails
  for any real entity id, cascading "Setup failed" into every downstream
  test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants (PRD §2.1) plus a non-binding fallback for
# the entity-backed RightsHolder role used ONLY for tests that do not
# exercise ownership (auth/role/404 negative tests).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "registration_reviewer_headers": build_user_headers(
        "reviewer-001", "RegistrationReviewer",
    ),
    "registration_reviewer_headers_alt": build_user_headers(
        "reviewer-002", "RegistrationReviewer",
    ),
    "finance_ops_headers": build_user_headers(
        "finance-ops-001", "FinanceOps",
    ),
    "finance_ops_headers_alt": build_user_headers(
        "finance-ops-002", "FinanceOps",
    ),
    "dispute_officer_headers": build_user_headers(
        "dispute-officer-001", "DisputeOfficer",
    ),
    "dispute_officer_headers_alt": build_user_headers(
        "dispute-officer-002", "DisputeOfficer",
    ),
    "playback_source_headers": build_user_headers(
        "spotify-us", "PlaybackSource",
    ),
    "playback_source_headers_alt": build_user_headers(
        "bbc-r2", "PlaybackSource",
    ),
    # Entity-backed fallback — use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource negatives).
    # The real X-User-ID for any ownership-gated call must equal the
    # persisted RightsHolder.id; the per-instance builder below is the
    # correct path.
    "rights_holder_headers": build_user_headers(
        "rights-holder-fallback", "RightsHolder",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. The RightsHolder entry is mandatory for every
# ownership-gated call; the opaque-role builders exist for convenience and
# parity, but are not required to thread an id.
# ---------------------------------------------------------------------------
def make_rights_holder_headers(holder_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is RightsHolder, X-User-ID is the id of
    the acting RightsHolder.' Pass the actual RightsHolder.id whenever the
    downstream call exercises an ownership check (work submit/withdraw,
    share edit on own work, dispute withdraw on own claim)."""
    return build_user_headers(holder_id, "RightsHolder")


def make_platform_admin_headers(
    user_id: str = "platform-admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is opaque."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_registration_reviewer_headers(
    user_id: str = "reviewer-001",
) -> Dict[str, str]:
    """PRD §2.1: RegistrationReviewer X-User-ID is opaque (recorded as
    reviewer_id on the Work but not compared)."""
    return build_user_headers(user_id, "RegistrationReviewer")


def make_finance_ops_headers(
    user_id: str = "finance-ops-001",
) -> Dict[str, str]:
    """PRD §2.1: FinanceOps X-User-ID is opaque."""
    return build_user_headers(user_id, "FinanceOps")


def make_dispute_officer_headers(
    user_id: str = "dispute-officer-001",
) -> Dict[str, str]:
    """PRD §2.1: DisputeOfficer X-User-ID is opaque (recorded as
    arbitrator_id but not compared)."""
    return build_user_headers(user_id, "DisputeOfficer")


def make_playback_source_headers(
    source_identifier: str = "spotify-us",
) -> Dict[str, str]:
    """PRD §2.1: PlaybackSource X-User-ID is an opaque source label.
    HMAC signature on the body, not the header, gates ingest."""
    return build_user_headers(source_identifier, "PlaybackSource")


__all__ = [
    "TEST_USERS",
    "make_rights_holder_headers",
    "make_platform_admin_headers",
    "make_registration_reviewer_headers",
    "make_finance_ops_headers",
    "make_dispute_officer_headers",
    "make_playback_source_headers",
]
