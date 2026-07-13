"""Pre-built role headers for every role in the PRD (PRD 2.1).

Five roles carry an opaque X-User-ID — AccountManager, DeliveryLead, Engineer,
FinanceOfficer and PlatformAdmin — and for them the shared constant is the
canonical form. The ClientContact role is entity-backed: its X-User-ID is the
`id` of the acting Client, and every ownership check compares that header to the
client foreign key of the target resource. Ownership-gated ClientContact calls
MUST therefore use make_client_contact_headers(client["id"]).

The opaque identities are also compared by the segregation-of-duties rules
(reviewer vs employee_user_id, signer vs assignee_user_id), so per-instance
builders exist for the Engineer and DeliveryLead roles too.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "account_manager_headers": build_user_headers("am-001", "AccountManager"),
    "delivery_lead_headers": build_user_headers("pm-001", "DeliveryLead"),
    "delivery_lead_2_headers": build_user_headers("pm-002", "DeliveryLead"),
    "engineer_headers": build_user_headers("eng-001", "Engineer"),
    "engineer_2_headers": build_user_headers("eng-002", "Engineer"),
    "finance_officer_headers": build_user_headers("fin-001", "FinanceOfficer"),
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    # entity_backed role: this shared constant never matches a real Client id, so
    # it is a fallback for non-ownership tests only (e.g. role-authorisation
    # rejections). Ownership-gated calls must use make_client_contact_headers().
    "client_contact_headers": build_user_headers("client-fallback-001", "ClientContact"),
}


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (identity = the acting Client). Pass the actual Client.id
    whenever the call is ownership-gated: signing an SOW, deciding a change
    request, accepting a release, raising a support incident, or any read of a
    resource that hangs off that client."""
    return build_user_headers(client_id, "ClientContact")


def make_engineer_headers(user_id: str) -> dict:
    """For Engineer (opaque). The X-User-ID is stamped as employee_user_id on a
    time entry and compared to the ticket's assignee_user_id, so callers that
    need a specific engineer identity pass it explicitly."""
    return build_user_headers(user_id, "Engineer")


def make_delivery_lead_headers(user_id: str) -> dict:
    """For DeliveryLead (opaque). The X-User-ID is recorded as
    reviewed_by_user_id and is compared to a time entry's employee_user_id by the
    segregation-of-duties rule."""
    return build_user_headers(user_id, "DeliveryLead")
