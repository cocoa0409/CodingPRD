"""Pre-built role headers for every role named in PRD 2.1.

`ClientContact` is entity-backed by `Client`: `X-User-ID` must be the acting
client's `id` whenever the call is ownership-scoped, so it has a per-instance
builder. The four firm-side roles carry opaque operator identifiers that are
never compared to any entity's `id`; their shared constants are canonical.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable operator identities used across the suite so segregation-of-duties
# checks (preparer != filer, submitter != certifier) have distinct X-User-IDs.
ANALYST_USER = "u_an1"
BROKER_USER = "u_br1"
BROKER_USER_2 = "u_br2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "firm_admin_headers": build_user_headers("u_admin1", "FirmAdmin"),
    "analyst_headers": build_user_headers(ANALYST_USER, "Analyst"),
    "broker_headers": build_user_headers(BROKER_USER, "LicensedBroker"),
    "broker2_headers": build_user_headers(BROKER_USER_2, "LicensedBroker"),
    "compliance_headers": build_user_headers("u_cm1", "ComplianceManager"),
    # Fallback for non-ownership calls only — never valid for an owned resource.
    "client_contact_headers": build_user_headers("test-client-contact-1", "ClientContact"),
}


def make_firm_admin_headers(user_id: str = "u_admin1") -> Dict[str, str]:
    return build_user_headers(user_id, "FirmAdmin")


def make_analyst_headers(user_id: str = ANALYST_USER) -> Dict[str, str]:
    return build_user_headers(user_id, "Analyst")


def make_broker_headers(user_id: str = BROKER_USER) -> Dict[str, str]:
    return build_user_headers(user_id, "LicensedBroker")


def make_compliance_headers(user_id: str = "u_cm1") -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceManager")


def make_client_contact_headers(client_id: str) -> Dict[str, str]:
    """For ClientContact (entity_backed:Client). Pass the acting Client.id
    whenever the call is ownership-scoped (PRD 2.1)."""
    return build_user_headers(client_id, "ClientContact")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
