"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, the Appraiser, LoanOfficer, ShopManager, and LawEnforcement
X-User-ID values are opaque operator identifiers not tied to any persisted
entity. The LoanOfficer's X-User-ID is compared against a pawn item's
appraised_by_user_id for the separation-of-duties control, so several flows
need to pin a specific operator id (e.g. an appraiser and an officer that
must differ). The per-user builders below produce headers with a chosen
operator id; the shared constants are used where the operator id is irrelevant.

The Customer role is entity_backed:Customer; its X-User-ID is the acting
Customer's id, so a per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — used where the specific opaque operator id is irrelevant
# (config setup, reads, 4xx-on-bad-input, role-denial checks).
TEST_USERS = {
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "officer_headers": build_user_headers("officer-1", "LoanOfficer"),
    "manager_headers": build_user_headers("manager-1", "ShopManager"),
    "law_headers": build_user_headers("law-1", "LawEnforcement"),
}


def make_appraiser_headers(user_id: str) -> dict:
    """Appraiser headers pinned to a chosen opaque operator id (PRD §2.1, §3.2)."""
    return build_user_headers(user_id, "Appraiser")


def make_officer_headers(user_id: str) -> dict:
    """LoanOfficer headers pinned to a chosen opaque operator id. Pin this to a
    value distinct from the appraiser to satisfy separation of duties (PRD §3.2),
    or equal to it to deliberately trip ERR_SEGREGATION_OF_DUTIES."""
    return build_user_headers(user_id, "LoanOfficer")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShopManager")


def make_law_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LawEnforcement")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity_backed:Customer (PRD §2.1) — pass the actual Customer.id."""
    return build_user_headers(customer_id, "Customer")
