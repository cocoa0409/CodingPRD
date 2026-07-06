"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque operator roles: shared constant is the canonical form.
    "registrar_headers": build_user_headers("registrar-1", "CityRegistrar"),
    "tax_officer_headers": build_user_headers("tax-officer-1", "TaxOfficer"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "host_headers": build_user_headers("host-fallback-1", "Host"),
    "platform_headers": build_user_headers("platform-fallback-1", "Platform"),
}


# Per-instance builders — required for every entity_backed role (Host, Platform).
def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id as user_id whenever
    the call is ownership-gated (activate, renew, remit, attest)."""
    return build_user_headers(user_id, "Host")


def make_platform_headers(user_id: str) -> dict:
    """For Platform (entity_backed:Platform). Pass the actual Platform.api_key/id
    as user_id when submitting listing reports."""
    return build_user_headers(user_id, "Platform")


def make_registrar_headers(user_id: str = "registrar-1") -> dict:
    return build_user_headers(user_id, "CityRegistrar")


def make_tax_officer_headers(user_id: str = "tax-officer-1") -> dict:
    return build_user_headers(user_id, "TaxOfficer")
