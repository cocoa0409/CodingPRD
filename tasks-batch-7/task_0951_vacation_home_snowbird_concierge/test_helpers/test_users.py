"""Pre-built role headers for every role named in the PRD.

Two roles bind their X-User-ID to a persisted row: Owner (to the Owner row's id)
and Vendor (to the Vendor row's id). For those two, ownership-gated calls MUST use
the per-instance builders below with the real entity id — the shared constants are
only safe for calls that never reach an ownership check.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the six opaque-identity roles, and for Owner/Vendor
# only on calls that do not perform an ownership comparison.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-platform-admin-1", "PlatformAdmin"),
    "account_manager_headers": build_user_headers("op-account-manager-1", "AccountManager"),
    "dispatcher_headers": build_user_headers("op-dispatcher-1", "Dispatcher"),
    "field_tech_headers": build_user_headers("op-field-tech-1", "FieldTech"),
    "storm_coordinator_headers": build_user_headers("op-storm-coordinator-1", "StormCoordinator"),
    "auditor_headers": build_user_headers("op-auditor-1", "Auditor"),
    # entity_backed roles: fallbacks for non-ownership tests only.
    "owner_headers": build_user_headers("op-owner-unbound-1", "Owner"),
    "vendor_headers": build_user_headers("op-vendor-unbound-1", "Vendor"),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ACCOUNT_MANAGER = TEST_USERS["account_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FIELD_TECH = TEST_USERS["field_tech_headers"]
STORM_COORDINATOR = TEST_USERS["storm_coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Two genuinely distinct field technicians. The segregation-of-duties rule
# requires the assessment signer to differ from the technician who swept.
TECH_ALPHA_ID = "tech-alpha"
TECH_BRAVO_ID = "tech-bravo"


def make_owner_headers(owner_id: str) -> dict:
    """For the Owner role. Pass the acting Owner row's id as X-User-ID."""
    return build_user_headers(owner_id, "Owner")


def make_vendor_headers(vendor_id: str) -> dict:
    """For the Vendor role. Pass the acting Vendor row's id as X-User-ID."""
    return build_user_headers(vendor_id, "Vendor")


def make_field_tech_headers(user_id: str) -> dict:
    """FieldTech is an opaque operator identity; the server records it as
    tech_user_id, swept_by_user_id or assessed_by_user_id."""
    return build_user_headers(user_id, "FieldTech")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_storm_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StormCoordinator")


def make_account_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary role/id pair — used by the authentication and unknown-role tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
