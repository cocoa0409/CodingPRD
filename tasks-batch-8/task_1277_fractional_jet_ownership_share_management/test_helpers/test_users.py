"""Pre-built role headers for every role in the PRD (§2.1).

The Owner role is entity-backed: when X-User-Role is Owner, X-User-ID must be
the id of the acting Owner record, so ownership-gated calls must be built with
make_owner_headers(owner["id"]). The operator roles are opaque identities.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "fleet_ops_headers": build_user_headers("test-fleetops-1", "FleetOps"),
    "finance_ops_headers": build_user_headers("test-finops-1", "FinanceOps"),
    # Entity-backed Owner role — fallback for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity-backed). Pass the actual Owner.id whenever the call
    is ownership-gated (booking create/confirm/cancel, invoice pay/dispute,
    listing create/accept/withdraw, share exit, exit withdraw)."""
    return build_user_headers(user_id, "Owner")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_fleet_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetOps")


def make_finance_ops_headers(user_id: str) -> dict:
    """For FinanceOps. Distinct identities matter for exit segregation of
    duties: the operator who valued an exit may not approve it (PRD §3.9)."""
    return build_user_headers(user_id, "FinanceOps")
