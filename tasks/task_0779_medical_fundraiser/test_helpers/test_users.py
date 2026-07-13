"""Pre-built role headers for every role in the PRD (PRD §2.1).

The six roles are: ``Guest``, ``Organizer``, ``Beneficiary``, ``Donor``,
``TrustSafetyAgent``, ``PlatformAdmin``.

- ``Guest``, ``TrustSafetyAgent`` and ``PlatformAdmin`` are OPAQUE roles: their
  ``X-User-ID`` is not tied to any persisted entity, so the shared constant is
  the canonical form.
- ``Organizer``, ``Beneficiary`` and ``Donor`` are ENTITY-BACKED: ``X-User-ID``
  must equal the ``id`` of an actual registered entity, because ownership /
  donor-identity checks compare a resource FK against ``X-User-ID``. For any
  ownership-gated success path the caller MUST use the per-instance builder
  ``make_<role>_headers(entity_id)`` — never the shared placeholder constant.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "guest_headers": build_user_headers("guest-1", "Guest"),
    "ts_agent_headers": build_user_headers("ts-agent-1", "TrustSafetyAgent"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Entity-backed roles — placeholder X-User-IDs. Safe ONLY for non-ownership
    # tests (401/403-wrong-role/404). Ownership-gated success paths must use the
    # per-instance builders below.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    "beneficiary_headers": build_user_headers("test-beneficiary-1", "Beneficiary"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_organizer_headers(user_id: str) -> dict:
    """Headers for an Organizer bound to a specific Organizer.id (PRD §2.1)."""
    return build_user_headers(user_id, "Organizer")


def make_beneficiary_headers(user_id: str) -> dict:
    """Headers for a Beneficiary bound to a specific Beneficiary.id (PRD §2.1)."""
    return build_user_headers(user_id, "Beneficiary")


def make_donor_headers(user_id: str) -> dict:
    """Headers for a Donor bound to a specific Donor.id (PRD §2.1)."""
    return build_user_headers(user_id, "Donor")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
