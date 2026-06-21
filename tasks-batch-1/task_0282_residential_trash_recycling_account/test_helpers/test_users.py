"""Pre-built role headers for every role in the PRD.

Dispatcher and CrewLead carry opaque X-User-ID (PRD §2.1) — the shared constant
is the canonical form. AccountHolder is entity_backed:ServiceAccount: ownership
checks compare the resource's account FK to X-User-ID, so ownership-gated calls
MUST use make_account_holder_headers(account_id) with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constant is canonical
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "crew_lead_headers": build_user_headers("crew-lead-1", "CrewLead"),
    # entity_backed role — shared constant is a fallback for non-ownership tests only
    # (e.g. 403 RBAC denials, 404 on missing resources).
    "account_holder_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000099", "AccountHolder"
    ),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity_backed:ServiceAccount). Pass the real
    ServiceAccount.id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "AccountHolder")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_crew_lead_headers(user_id: str = "crew-lead-1") -> dict:
    return build_user_headers(user_id, "CrewLead")
