"""Pre-built role headers for every role the PRD recognises (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities. PRD §2.1: for HostOperations, HostController and
# ComplianceOfficer the X-User-ID is an opaque operator identifier that is never
# compared against any row's id, so these shared constants are canonical.
#
# Two distinct HostController users exist because PRD §2.11 forbids the
# X-User-ID that calculated a run from posting it.
TEST_USERS = {
    "host_operations_headers": build_user_headers("ops-1", "HostOperations"),
    "host_controller_headers": build_user_headers("ctrl-1", "HostController"),
    "host_controller_2_headers": build_user_headers("ctrl-2", "HostController"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    # Entity-backed roles: these shared constants are a fallback for tests that
    # do not exercise ownership (unknown-role, missing-header, 404 probes).
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    "supplier_portal_headers": build_user_headers("test-supplier-1", "SupplierPortal"),
}

OPS_USER_ID = "ops-1"
CONTROLLER_CALC_USER_ID = "ctrl-1"
CONTROLLER_POST_USER_ID = "ctrl-2"
COMPLIANCE_USER_ID = "co-1"


def make_advisor_headers(advisor_id: str) -> dict:
    """Headers for role Advisor. PRD §2.1: when X-User-Role is Advisor, X-User-ID
    is the id of the acting Advisor row, so pass the real advisor id whenever the
    call is ownership-gated."""
    return build_user_headers(advisor_id, "Advisor")


def make_supplier_portal_headers(supplier_id: str) -> dict:
    """Headers for role SupplierPortal. PRD §2.1: when X-User-Role is
    SupplierPortal, X-User-ID is the id of the acting Supplier row."""
    return build_user_headers(supplier_id, "SupplierPortal")


def make_host_operations_headers(user_id: str = OPS_USER_ID) -> dict:
    """Headers for role HostOperations with a caller-chosen operator id."""
    return build_user_headers(user_id, "HostOperations")


def make_host_controller_headers(user_id: str = CONTROLLER_CALC_USER_ID) -> dict:
    """Headers for role HostController with a caller-chosen operator id."""
    return build_user_headers(user_id, "HostController")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    """Headers for role ComplianceOfficer with a caller-chosen operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def ops_headers() -> dict:
    return TEST_USERS["host_operations_headers"]


def controller_headers() -> dict:
    return TEST_USERS["host_controller_headers"]


def controller_2_headers() -> dict:
    return TEST_USERS["host_controller_2_headers"]


def compliance_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]
