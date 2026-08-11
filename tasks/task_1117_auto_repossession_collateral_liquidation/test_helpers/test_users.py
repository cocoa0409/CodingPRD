"""Pre-built role headers for every role in the PRD (PRD §2.1).

RepoAgent, Auctioneer, and Borrower are entity-backed identities: their
X-User-ID must equal the id of the entity they act as. Always use the
per-instance builders (make_*_headers) with the real entity id for
ownership-gated calls; the shared constants are fallbacks for tests whose
outcome does not depend on ownership (e.g. 400 / 404 / role rejections).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import CO_OPERATOR_ALT_ID, CO_OPERATOR_ID, RM_OPERATOR_ID

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "recovery_manager_headers": build_user_headers(RM_OPERATOR_ID, "RecoveryManager"),
    "compliance_officer_headers": build_user_headers(CO_OPERATOR_ID, "ComplianceOfficer"),
    "compliance_officer_alt_headers": build_user_headers(CO_OPERATOR_ALT_ID, "ComplianceOfficer"),
    # Entity-backed roles — shared constants only for non-ownership tests.
    "repo_agent_headers": build_user_headers("test-agent-1", "RepoAgent"),
    "auctioneer_headers": build_user_headers("test-auctioneer-1", "Auctioneer"),
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
}


def make_recovery_manager_headers(user_id: str = RM_OPERATOR_ID) -> dict:
    """RecoveryManager is an opaque identity (PRD §2.1); the value is stamped
    as opened_by_user_id on every case the caller opens."""
    return build_user_headers(user_id, "RecoveryManager")


def make_compliance_officer_headers(user_id: str = CO_OPERATOR_ID) -> dict:
    """ComplianceOfficer is an opaque identity (PRD §2.1)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_agent_headers(agent_id: str) -> dict:
    """RepoAgent is entity-backed: pass the real RepoAgent.id whenever the
    call is ownership-gated (accept, report-secured, mark-returned, dispose)."""
    return build_user_headers(agent_id, "RepoAgent")


def make_auctioneer_headers(auction_house_id: str) -> dict:
    """Auctioneer is entity-backed: pass the real AuctionHouse.id whenever the
    call is ownership-gated (list, relist, report-sale, report-unsold)."""
    return build_user_headers(auction_house_id, "Auctioneer")


def make_borrower_headers(borrower_id: str) -> dict:
    """Borrower is entity-backed: pass the real Borrower.id whenever the call
    is ownership-gated (cure payments, quote accept, complaints, item
    claim/unclaim, deficiency dispute/payment)."""
    return build_user_headers(borrower_id, "Borrower")
