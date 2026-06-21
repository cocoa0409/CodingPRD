"""Pre-built role headers for every role in the PRD.

The platform recognizes exactly five roles. Three are opaque (PlatformAdmin,
TrustOfficer, Arbiter): their X-User-ID is an operator identifier never compared
to any entity id, so a shared constant is the canonical form. Two are
entity-backed (Tutor -> Tutor.id, ParentGuardian -> ParentAccount.id): for
ownership-gated calls a per-instance builder must be used with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - Opaque roles: canonical form (X-User-ID is just an operator id).
#   - Entity-backed roles: a fallback only for non-ownership tests (e.g. 400 on
#     bad payload, 404 on missing resource, or authorization-only checks). Any
#     ownership-gated call must instead use the matching make_*_headers builder.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    "trust_officer_headers": build_user_headers("trust-officer-1", "TrustOfficer"),
    "arbiter_headers": build_user_headers("arbiter-1", "Arbiter"),
    "tutor_headers": build_user_headers("tutor-placeholder-1", "Tutor"),
    "parent_headers": build_user_headers("parent-placeholder-1", "ParentGuardian"),
}


def make_platform_admin_headers() -> dict:
    """Opaque PlatformAdmin headers (X-User-ID not tied to any entity)."""
    return TEST_USERS["platform_admin_headers"]


def make_trust_officer_headers() -> dict:
    """Opaque TrustOfficer headers (X-User-ID not tied to any entity)."""
    return TEST_USERS["trust_officer_headers"]


def make_arbiter_headers() -> dict:
    """Opaque Arbiter headers (X-User-ID not tied to any entity)."""
    return TEST_USERS["arbiter_headers"]


def make_tutor_headers(tutor_id: str) -> dict:
    """For Tutor (entity_backed:Tutor). Pass the acting Tutor.id as X-User-ID
    whenever the call is ownership-gated (own credentials, tags, sessions, and
    the responding side of a refund case)."""
    return build_user_headers(tutor_id, "Tutor")


def make_parent_headers(parent_account_id: str) -> dict:
    """For ParentGuardian (entity_backed:ParentAccount). Pass the acting
    ParentAccount.id as X-User-ID whenever the call is ownership-gated (own
    students, bookings, and the claimant side of a refund case)."""
    return build_user_headers(parent_account_id, "ParentGuardian")
