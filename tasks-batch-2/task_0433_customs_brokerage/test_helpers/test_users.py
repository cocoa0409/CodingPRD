"""Pre-built role headers for every role in the PRD.

Three of the four roles (AccountAdmin, LicensedBroker, CBPOfficer) are opaque:
their X-User-ID is an operator identifier the server never compares to any
entity id. Only ImporterUser is entity-backed (X-User-ID is compared to the
acting importer's owner_user_id), so it gets a per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these as their canonical form; the
# entity-backed ImporterUser constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "AccountAdmin"),
    "broker_headers": build_user_headers("broker-1", "LicensedBroker"),
    "officer_headers": build_user_headers("officer-1", "CBPOfficer"),
    # Second officer, distinct X-User-ID, for segregation-of-duties scenarios.
    "officer2_headers": build_user_headers("officer-2", "CBPOfficer"),
    # Fallback ImporterUser constant — only for tests that do not exercise ownership.
    "importer_user_headers": build_user_headers("imp-user-1", "ImporterUser"),
}


# Per-instance builders.
def make_admin_headers(user_id: str = "admin-1") -> dict:
    """AccountAdmin (opaque). X-User-ID is not entity-compared."""
    return build_user_headers(user_id, "AccountAdmin")


def make_broker_headers(user_id: str = "broker-1") -> dict:
    """LicensedBroker (opaque). X-User-ID is recorded as filed_by_user_id but
    never compared to an entity id."""
    return build_user_headers(user_id, "LicensedBroker")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """CBPOfficer (opaque). X-User-ID is recorded as reviewed_by_user_id but
    never compared to an entity id."""
    return build_user_headers(user_id, "CBPOfficer")


def make_importer_user_headers(owner_user_id: str) -> dict:
    """ImporterUser (entity_backed:Importer). Pass the importer's owner_user_id
    so ownership checks (owner_user_id == X-User-ID) pass."""
    return build_user_headers(owner_user_id, "ImporterUser")
