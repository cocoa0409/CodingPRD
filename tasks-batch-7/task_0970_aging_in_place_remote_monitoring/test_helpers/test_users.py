"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership checks.
TEST_USERS = {
    # opaque roles: canonical form
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "monitoring_agent_headers": build_user_headers("test-agent-1", "MonitoringAgent"),
    "device_hub_headers": build_user_headers("test-device-hub-1", "DeviceHub"),
    # entity_backed roles: fallback only for non-ownership tests (400/404 paths).
    "caregiver_headers": build_user_headers("test-caregiver-1", "Caregiver"),
    "senior_headers": build_user_headers("test-senior-1", "Senior"),
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
}


# Per-instance builders — required for entity_backed roles whenever the call is
# ownership-gated: pass the actual persisted entity id as user_id.


def make_caregiver_headers(user_id: str) -> dict:
    """Caregiver is entity-backed: X-User-ID must be the acting Caregiver's id."""
    return build_user_headers(user_id, "Caregiver")


def make_senior_headers(user_id: str) -> dict:
    """Senior is entity-backed: X-User-ID must be the acting Senior's id."""
    return build_user_headers(user_id, "Senior")


def make_installer_headers(user_id: str) -> dict:
    """Installer is entity-backed: X-User-ID must be the acting Installer's id."""
    return build_user_headers(user_id, "Installer")
