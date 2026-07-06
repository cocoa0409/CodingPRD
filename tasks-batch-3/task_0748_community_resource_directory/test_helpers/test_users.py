"""Pre-built role headers for every PRD role.

PRD §2.1 distinguishes:
- Opaque roles (PlatformAdmin, Caseworker): X-User-ID is an opaque operator id.
- Entity-backed roles (ProviderStaff, Client, FunderReporter): X-User-ID must equal
  the id of the acting Provider / Client / Funder for ownership checks.

Fixtures MUST use make_provider_headers/make_client_headers/make_funder_reporter_headers
with the entity's actual id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for negative tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    "caseworker_headers": build_user_headers("test-caseworker", "Caseworker"),

    # Entity-backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g., role-membership 403 / bad-payload 400). Real ownership calls MUST use
    # the make_* helpers below with a persisted entity id.
    "provider_staff_headers": build_user_headers("test-provider-staff", "ProviderStaff"),
    "client_headers": build_user_headers("test-client", "Client"),
    "funder_reporter_headers": build_user_headers("test-funder-reporter", "FunderReporter"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin") -> dict:
    """PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_caseworker_headers(user_id: str = "test-caseworker") -> dict:
    """Caseworker (opaque identity)."""
    return build_user_headers(user_id, "Caseworker")


def make_provider_staff_headers(provider_id: str) -> dict:
    """ProviderStaff (entity_backed:Provider). Pass the actual Provider.id."""
    return build_user_headers(provider_id, "ProviderStaff")


def make_client_headers(client_id: str) -> dict:
    """Client (entity_backed:Client). Pass the actual Client.id."""
    return build_user_headers(client_id, "Client")


def make_funder_reporter_headers(funder_id: str) -> dict:
    """FunderReporter (entity_backed:Funder). Pass the actual Funder.id."""
    return build_user_headers(funder_id, "FunderReporter")
