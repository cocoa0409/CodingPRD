"""Pre-built role headers for every role named in PRD 2.1.

All four roles have an opaque identity: `X-User-ID` is an opaque operator
identifier that the server never compares to any resource's id, so the shared
constants below are the canonical form for every call.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    "harvest_operator_headers": build_user_headers("operator-1", "HarvestOperator"),
    "grower_liaison_headers": build_user_headers("liaison-1", "GrowerLiaison"),
    "crew_boss_headers": build_user_headers("boss-1", "CrewBoss"),
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
}


def make_harvest_operator_headers(user_id: str = "operator-1") -> Dict[str, str]:
    return build_user_headers(user_id, "HarvestOperator")


def make_grower_liaison_headers(user_id: str = "liaison-1") -> Dict[str, str]:
    return build_user_headers(user_id, "GrowerLiaison")


def make_crew_boss_headers(user_id: str = "boss-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CrewBoss")


def make_billing_clerk_headers(user_id: str = "clerk-1") -> Dict[str, str]:
    return build_user_headers(user_id, "BillingClerk")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
