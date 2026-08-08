"""Pre-built role headers for every role in the PRD.

All five roles use an OPAQUE X-User-ID (PRD §2.1): the server never resolves it
to a stored entity. It is, however, recorded where the workflow calls for it
(inspected_by_user_id, issued_by_user_id, hearing_officer_id) and drives the
segregation-of-duties rule (PRD §3.6). Tests therefore sometimes need to control
the exact X-User-ID, so per-role builders are provided alongside shared defaults.
"""
from prd_bench_local_runner.testing import build_user_headers

# Default operator identifiers used across setup chains.
DEFAULT_OFFICER_ID = "officer-1"
DEFAULT_HEARING_OFFICER_ID = "hof-9"
DEFAULT_CLERK_ID = "clerk-1"
DEFAULT_RESIDENT_ID = "resident-1"
DEFAULT_ADMIN_ID = "admin-1"

TEST_USERS = {
    "code_officer_headers": build_user_headers(DEFAULT_OFFICER_ID, "CodeOfficer"),
    "hearing_officer_headers": build_user_headers(DEFAULT_HEARING_OFFICER_ID, "HearingOfficer"),
    "permit_clerk_headers": build_user_headers(DEFAULT_CLERK_ID, "PermitClerk"),
    "resident_headers": build_user_headers(DEFAULT_RESIDENT_ID, "Resident"),
    "system_admin_headers": build_user_headers(DEFAULT_ADMIN_ID, "SystemAdmin"),
}


def code_officer_headers(user_id: str = DEFAULT_OFFICER_ID) -> dict:
    """CodeOfficer headers with a controllable X-User-ID (issuer of enforcements)."""
    return build_user_headers(user_id, "CodeOfficer")


def hearing_officer_headers(user_id: str = DEFAULT_HEARING_OFFICER_ID) -> dict:
    """HearingOfficer headers with a controllable X-User-ID (hearing decider / SoD)."""
    return build_user_headers(user_id, "HearingOfficer")


def permit_clerk_headers(user_id: str = DEFAULT_CLERK_ID) -> dict:
    return build_user_headers(user_id, "PermitClerk")


def resident_headers(user_id: str = DEFAULT_RESIDENT_ID) -> dict:
    return build_user_headers(user_id, "Resident")


def system_admin_headers(user_id: str = DEFAULT_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
