"""Pre-built role headers for the four roles the PRD recognises (PRD §2.1).

PRD §2.1: the four roles — `Dispatcher`, `Arborist`, `FinanceClerk`, and
`Client` — are all opaque identities; `X-User-ID` is never the primary key of
a persisted role entity. For `Dispatcher`, `Arborist`, and `FinanceClerk` the
header merely authorizes the action and is never compared against a stored id.

For `Client`, the value still carries ownership meaning: a work order records
its owning customer's identifier as `client_user_id` from the create body, and
ownership checks on estimate accept/decline compare the acting Client's
`X-User-ID` against that stored `client_user_id` string (not a foreign key).
A Client acting on a work order it does not own is rejected with
`ERR_NOT_RESOURCE_OWNER`. Use ``make_client_headers(client_user_id)`` to act
as a specific owning customer; the shared constant below uses the canonical
"client-1" identifier that fixtures stamp onto every work order they create.
"""
from prd_bench_local_runner.testing import build_user_headers


# Canonical client identifier that fixtures stamp onto created work orders.
DEFAULT_CLIENT_USER_ID = "client-1"


TEST_USERS = {
    "dispatcher_headers": build_user_headers("dispatcher-test-1", "Dispatcher"),
    "arborist_headers": build_user_headers("arborist-test-1", "Arborist"),
    "finance_clerk_headers": build_user_headers("finance-clerk-test-1", "FinanceClerk"),
    # Client whose X-User-ID equals the default owner stamped by fixtures.
    "client_headers": build_user_headers(DEFAULT_CLIENT_USER_ID, "Client"),
}


def make_client_headers(client_user_id: str) -> dict:
    """For Client-role calls whose success depends on owning the work order
    (PRD §2.1: estimate accept/decline compare X-User-ID against the stored
    `client_user_id`). Pass the work order's `client_user_id` so the
    ownership check passes."""
    return build_user_headers(client_user_id, "Client")


def make_dispatcher_headers(user_id: str = "dispatcher-test-1") -> dict:
    """Per-instance builder for the opaque Dispatcher role."""
    return build_user_headers(user_id, "Dispatcher")


def make_arborist_headers(user_id: str = "arborist-test-1") -> dict:
    """Per-instance builder for the opaque Arborist role."""
    return build_user_headers(user_id, "Arborist")


def make_finance_clerk_headers(user_id: str = "finance-clerk-test-1") -> dict:
    """Per-instance builder for the opaque FinanceClerk role."""
    return build_user_headers(user_id, "FinanceClerk")
