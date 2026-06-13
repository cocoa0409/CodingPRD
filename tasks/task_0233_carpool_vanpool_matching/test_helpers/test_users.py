"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# PlatformOps and ProgramAdmin carry opaque operator identifiers not tied to any
# persisted entity (PRD §2.1), so a shared constant is the canonical form for them.
# The Driver / Rider shared constants are fallbacks for non-ownership tests only
# (e.g. 401/403/404/422 probes) — any ownership-gated Driver/Rider call MUST use
# make_driver_headers(member_id) / make_rider_headers(member_id) instead, because
# Driver and Rider are entity_backed:Member and X-User-ID must equal the Member id.
TEST_USERS = {
    "platform_ops_headers": build_user_headers("test-platform-ops-1", "PlatformOps"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "driver_headers": build_user_headers("test-driver-fallback-1", "Driver"),
    "rider_headers": build_user_headers("test-rider-fallback-1", "Rider"),
}


def make_platform_ops_headers(user_id: str = "test-platform-ops-1") -> dict:
    """PlatformOps is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "PlatformOps")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    """ProgramAdmin is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Member). Pass the driving Member.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Driver")


def make_rider_headers(user_id: str) -> dict:
    """For Rider (entity_backed:Member). Pass the riding Member.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Rider")
