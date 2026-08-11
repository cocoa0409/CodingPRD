"""Pre-built role headers for every role in the PRD (§2.1, §4).

Vendor is entity-backed: when a call is ownership-gated (an application,
assignment, settlement, or ledger entry owned by a VendorProfile), build
headers with make_vendor_headers(vendor_profile_id). The shared
"vendor_headers" constant is only for calls whose outcome does not depend
on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400/404/role-denial probes).
TEST_USERS = {
    "event_coordinator_headers": build_user_headers("coordinator-1", "EventCoordinator"),
    "treasurer_headers": build_user_headers("treasurer-1", "Treasurer"),
    "juror_headers": build_user_headers("juror-1", "Juror"),
    "juror_2_headers": build_user_headers("juror-2", "Juror"),
    "gate_agent_headers": build_user_headers("gate-agent-1", "GateAgent"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # entity-backed role: shared constant is a fallback for non-ownership tests only.
    "vendor_headers": build_user_headers("vendor-shared-1", "Vendor"),
}


# Per-instance builders — required whenever the call is ownership-gated.

def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed by VendorProfile: pass the actual VendorProfile.id
    whenever the call is ownership-gated (applications, pay, ledger, dispute...)."""
    return build_user_headers(user_id, "Vendor")


def make_event_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EventCoordinator")


def make_treasurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Treasurer")


def make_juror_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Juror")


def make_gate_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GateAgent")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
