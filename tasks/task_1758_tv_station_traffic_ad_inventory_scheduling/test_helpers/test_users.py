"""Pre-built role headers for every role in the PRD (§2.1).

All five roles carry opaque operator identifiers: the server never compares
X-User-ID against any resource id, so the shared constants below are the
canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "salesrep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "trafficmanager_headers": build_user_headers("test-traffic-1", "TrafficManager"),
    "copycoordinator_headers": build_user_headers("test-copy-1", "CopyCoordinator"),
    "billingclerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "stationadmin_headers": build_user_headers("test-admin-1", "StationAdmin"),
}

# Requests with no authentication headers at all (PRD §2.1).
NO_AUTH_HEADERS: dict = {}


def make_salesrep_headers(user_id: str = "test-salesrep-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_trafficmanager_headers(user_id: str = "test-traffic-1") -> dict:
    return build_user_headers(user_id, "TrafficManager")


def make_copycoordinator_headers(user_id: str = "test-copy-1") -> dict:
    return build_user_headers(user_id, "CopyCoordinator")


def make_billingclerk_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_stationadmin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "StationAdmin")
