"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (Registrar, Tenant) and for tests
# that do NOT exercise ownership. Landlord/Inspector are entity_backed: their
# shared constant is a fallback for non-ownership tests only; ownership-gated
# calls MUST use make_landlord_headers()/make_inspector_headers() with a real id.
TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "tenant_headers": build_user_headers("tenant-1", "Tenant"),
    "landlord_headers": build_user_headers("landlord-shared", "Landlord"),
    "inspector_headers": build_user_headers("inspector-shared", "Inspector"),
    # Unknown role, for ERR_UNAUTHENTICATED tests.
    "unknown_headers": build_user_headers("nobody-1", "Nobody"),
}


# Per-instance builders — required for every entity_backed role.
def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the owning Landlord.id
    whenever the call is ownership-gated (property, pay, remediation)."""
    return build_user_headers(user_id, "Landlord")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the assigned Inspector.id
    whenever the call is ownership-gated (begin, checklist-items, complete)."""
    return build_user_headers(user_id, "Inspector")


def make_registrar_headers(user_id: str = "registrar-1") -> dict:
    return build_user_headers(user_id, "Registrar")


def make_tenant_headers(user_id: str = "tenant-1") -> dict:
    return build_user_headers(user_id, "Tenant")
