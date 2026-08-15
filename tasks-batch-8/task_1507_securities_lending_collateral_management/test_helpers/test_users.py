"""Pre-built role headers for every role in the PRD.

DeskTrader, RiskOfficer, OpsSettler, and DeskAdmin are opaque roles:
X-User-ID is an operator identifier never compared to an entity id.

BorrowerRep and OwnerRep are entity-backed: X-User-ID must equal the
acting Borrower.id / BeneficialOwner.id. Any ownership-gated call MUST use
make_borrower_rep_headers(borrower["id"]) / make_owner_rep_headers(owner["id"])
with the real entity id — the shared constants below are only for tests
whose outcome does not depend on ownership (role-denied, 400, 404 tests).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (bad-payload 400s, missing-resource 404s, role denials).
TEST_USERS = {
    "desk_trader_headers": build_user_headers("test-trader-1", "DeskTrader"),
    "borrower_rep_headers": build_user_headers("test-borrower-1", "BorrowerRep"),
    "owner_rep_headers": build_user_headers("test-owner-1", "OwnerRep"),
    "risk_officer_headers": build_user_headers("test-risk-1", "RiskOfficer"),
    "ops_settler_headers": build_user_headers("test-ops-1", "OpsSettler"),
    "desk_admin_headers": build_user_headers("test-admin-1", "DeskAdmin"),
}


# Per-instance builders — required for the two entity-backed roles whenever
# the call is ownership-gated.

def make_borrower_rep_headers(user_id: str) -> dict:
    """BorrowerRep is entity-backed by Borrower: pass the real Borrower.id
    whenever the request touches that borrower's resources."""
    return build_user_headers(user_id, "BorrowerRep")


def make_owner_rep_headers(user_id: str) -> dict:
    """OwnerRep is entity-backed by BeneficialOwner: pass the real
    BeneficialOwner.id whenever the request touches that owner's resources."""
    return build_user_headers(user_id, "OwnerRep")


def make_desk_trader_headers(user_id: str) -> dict:
    """Opaque role: distinct user ids matter for segregation-of-duties
    (override requester vs approver)."""
    return build_user_headers(user_id, "DeskTrader")


def make_risk_officer_headers(user_id: str) -> dict:
    """Opaque role: distinct user ids matter for segregation-of-duties."""
    return build_user_headers(user_id, "RiskOfficer")


def make_ops_settler_headers(user_id: str) -> dict:
    """Opaque role: distinct user ids matter for report finalize/file SoD."""
    return build_user_headers(user_id, "OpsSettler")


def make_desk_admin_headers(user_id: str) -> dict:
    """Opaque role: distinct user ids matter for report finalize/file SoD."""
    return build_user_headers(user_id, "DeskAdmin")


# Headers with no X-User-Role at all -> ERR_UNAUTHENTICATED territory.
ANONYMOUS_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
