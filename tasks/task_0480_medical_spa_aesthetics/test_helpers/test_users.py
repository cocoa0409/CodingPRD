"""Pre-built role headers for every role in the PRD (§2.1).

There are two roles: ClinicAdmin (opaque X-User-ID — never compared to any
entity) and Provider (entity_backed — X-User-ID is the acting Provider.id, and
ownership/segregation checks compare resource provider FKs to it). Therefore
every ownership-gated Provider call MUST use make_provider_headers(provider_id);
the shared PROVIDER constant is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    # entity_backed Provider: fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_clinic_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ClinicAdmin headers (opaque operator id; not compared to any entity)."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_provider_headers(user_id: str) -> dict:
    """For the Provider role (entity_backed:Provider). Pass the actual
    Provider.id as user_id for any ownership/segregation-gated clinical call."""
    return build_user_headers(user_id, "Provider")
