"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, PlatformAdmin) and for
# tests that do NOT exercise ownership (400/403/404 on missing or wrong-role).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallbacks for entity_backed roles — non-ownership tests ONLY.
    "homeowner_headers": build_user_headers("homeowner-fallback-1", "Homeowner"),
    "installer_headers": build_user_headers("installer-fallback-1", "SolarInstaller"),
    "utility_headers": build_user_headers("utility-fallback-1", "Utility"),
    "broker_headers": build_user_headers("broker-fallback-1", "SrecBroker"),
}


# Per-instance builders — required for every entity_backed role.
def make_homeowner_headers(user_id: str) -> dict:
    """Homeowner (entity_backed:Homeowner). Pass the actual Homeowner.id."""
    return build_user_headers(user_id, "Homeowner")


def make_installer_headers(user_id: str) -> dict:
    """SolarInstaller (entity_backed:SolarInstaller). Pass the actual SolarInstaller.id."""
    return build_user_headers(user_id, "SolarInstaller")


def make_utility_headers(user_id: str) -> dict:
    """Utility (entity_backed:Utility). Pass the actual Utility.id."""
    return build_user_headers(user_id, "Utility")


def make_broker_headers(user_id: str) -> dict:
    """SrecBroker (entity_backed:SrecBroker). Pass the actual SrecBroker.id."""
    return build_user_headers(user_id, "SrecBroker")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """PlatformAdmin (opaque). Identifier is not tied to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
