"""Pre-built role headers for every role in the PRD (§2.1).

`ProgramAdministrator` and `ProgramAuditor` are opaque roles: their X-User-ID is
an operator identifier never compared to an entity id, so the shared constants
below are the canonical form for them.

`Registrant`, `CollectionSiteOperator`, `Hauler` and `Recycler` are entity-backed:
their X-User-ID is the id of the acting entity. Ownership-gated calls MUST use the
matching `make_*_headers(entity_id)` builder with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Shared constants.
#
# Safe for the two opaque roles, and for tests that never exercise ownership
# (missing-payload rejections, unknown-id lookups, role-membership rejections).
# ---------------------------------------------------------------------------
TEST_USERS = {
    # Opaque operator identities. Three administrators so segregation of duties
    # (proposer vs approver) and two auditors (requester vs closer) are testable.
    "admin_headers": build_user_headers("admin-1", "ProgramAdministrator"),
    "admin_2_headers": build_user_headers("admin-2", "ProgramAdministrator"),
    "admin_3_headers": build_user_headers("admin-3", "ProgramAdministrator"),
    "auditor_headers": build_user_headers("auditor-1", "ProgramAuditor"),
    "auditor_2_headers": build_user_headers("auditor-2", "ProgramAuditor"),
    # Entity-backed fallbacks — non-ownership tests only.
    "registrant_headers": build_user_headers("test-registrant-1", "Registrant"),
    "site_operator_headers": build_user_headers(
        "test-site-1", "CollectionSiteOperator"
    ),
    "hauler_headers": build_user_headers("test-hauler-1", "Hauler"),
    "recycler_headers": build_user_headers("test-recycler-1", "Recycler"),
}

# Opaque operator identifiers, exposed so tests can assert audit-trail fields.
ADMIN_1_USER_ID = "admin-1"
ADMIN_2_USER_ID = "admin-2"
ADMIN_3_USER_ID = "admin-3"
AUDITOR_1_USER_ID = "auditor-1"
AUDITOR_2_USER_ID = "auditor-2"

# A request that omits both headers (PRD §2.1 authentication).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_admin_headers(user_id: str) -> dict:
    """For ProgramAdministrator (opaque). Any operator identifier is acceptable."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_auditor_headers(user_id: str) -> dict:
    """For ProgramAuditor (opaque). Any operator identifier is acceptable."""
    return build_user_headers(user_id, "ProgramAuditor")


def make_registrant_headers(user_id: str) -> dict:
    """For Registrant (entity-backed). Pass the actual Registrant.id."""
    return build_user_headers(user_id, "Registrant")


def make_site_operator_headers(user_id: str) -> dict:
    """For CollectionSiteOperator (entity-backed). Pass the actual CollectionSite.id."""
    return build_user_headers(user_id, "CollectionSiteOperator")


def make_hauler_headers(user_id: str) -> dict:
    """For Hauler (entity-backed). Pass the actual Hauler.id."""
    return build_user_headers(user_id, "Hauler")


def make_recycler_headers(user_id: str) -> dict:
    """For Recycler (entity-backed). Pass the actual Recycler.id."""
    return build_user_headers(user_id, "Recycler")


def make_unrecognised_role_headers(user_id: str = "admin-1") -> dict:
    """Headers declaring an X-User-Role value the server does not recognise."""
    return build_user_headers(user_id, "MattressCzar")
