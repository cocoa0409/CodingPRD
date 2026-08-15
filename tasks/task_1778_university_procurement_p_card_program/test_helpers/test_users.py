"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants use fixed operator ids that never collide with the default
requester id, so segregation-of-duties checks do not fire accidentally.
The Cardholder role is entity-backed: its X-User-ID IS the PCard id, so
ownership-gated calls MUST use make_cardholder_headers(card["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — safe shared constants for non-ownership calls.
    "requester_headers": build_user_headers("req-user-1", "Requester"),
    "requester2_headers": build_user_headers("req-user-2", "Requester"),
    "department_approver_headers": build_user_headers(
        "dept-approver-1", "DepartmentApprover"
    ),
    "buyer_headers": build_user_headers("buyer-1", "Buyer"),
    "director_headers": build_user_headers("director-1", "ProcurementDirector"),
    "contract_officer_headers": build_user_headers(
        "contract-officer-1", "ContractOfficer"
    ),
    "grant_officer_headers": build_user_headers("grant-officer-1", "GrantOfficer"),
    "ap_clerk_headers": build_user_headers("ap-1", "APClerk"),
    "receiving_clerk_headers": build_user_headers("receiving-1", "ReceivingClerk"),
    "surplus_manager_headers": build_user_headers("surplus-1", "SurplusManager"),
    "admin_headers": build_user_headers("admin-1", "ProcurementAdmin"),
    # Fallback only for non-ownership contexts; real card calls must use the
    # per-instance builder below with the actual PCard id.
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
}


def make_requester_headers(user_id: str) -> dict:
    """Requester headers for a specific operator id (requisition ownership)."""
    return build_user_headers(user_id, "Requester")


def make_cardholder_headers(pcard_id: str) -> dict:
    """Cardholder identity is the PCard id itself (PRD §2.1). Pass the actual
    PCard.id whenever the call is ownership-gated (post/reconcile/dispute)."""
    return build_user_headers(pcard_id, "Cardholder")


def make_role_headers(user_id: str, role: str) -> dict:
    """Generic builder for ad-hoc identities (e.g., self-approval probes)."""
    return build_user_headers(user_id, role)
