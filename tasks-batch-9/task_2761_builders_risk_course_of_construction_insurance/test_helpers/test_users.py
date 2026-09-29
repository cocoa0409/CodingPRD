"""Pre-built request headers for every role named in the PRD.

Four roles (Underwriter, UnderwritingManager, RiskEngineer, ClaimAdjuster) carry
an opaque operator identifier, so the shared constants below are the canonical
form for them. ProjectContact and LossPayee are entity-backed: their X-User-ID is
the id of the acting ConstructionProject / NamedInsuredInterest, so ownership
gated calls MUST use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities. Two distinct users per maker-checker role so a
    # test can exercise segregation of duties in either direction.
    "underwriter_headers": build_user_headers("uw-001", "Underwriter"),
    "underwriter_2_headers": build_user_headers("uw-002", "Underwriter"),
    "manager_headers": build_user_headers("um-001", "UnderwritingManager"),
    "manager_2_headers": build_user_headers("um-002", "UnderwritingManager"),
    "risk_engineer_headers": build_user_headers("re-001", "RiskEngineer"),
    "risk_engineer_2_headers": build_user_headers("re-002", "RiskEngineer"),
    "claim_adjuster_headers": build_user_headers("ca-001", "ClaimAdjuster"),
    "claim_adjuster_2_headers": build_user_headers("ca-002", "ClaimAdjuster"),
    # Entity-backed roles: these shared constants are only safe for tests that do
    # not depend on the caller owning the subject resource (a 401/403/404 probe).
    "project_contact_headers": build_user_headers("pc-unowned", "ProjectContact"),
    "loss_payee_headers": build_user_headers("lp-unowned", "LossPayee"),
}

UNDERWRITER_ID = "uw-001"
UNDERWRITER_2_ID = "uw-002"
MANAGER_ID = "um-001"
MANAGER_2_ID = "um-002"
RISK_ENGINEER_ID = "re-001"
CLAIM_ADJUSTER_ID = "ca-001"
CLAIM_ADJUSTER_2_ID = "ca-002"


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter acting as an arbitrary operator id."""
    return build_user_headers(user_id, "Underwriter")


def make_manager_headers(user_id: str) -> dict:
    """UnderwritingManager acting as an arbitrary operator id."""
    return build_user_headers(user_id, "UnderwritingManager")


def make_risk_engineer_headers(user_id: str) -> dict:
    """RiskEngineer acting as an arbitrary operator id."""
    return build_user_headers(user_id, "RiskEngineer")


def make_claim_adjuster_headers(user_id: str) -> dict:
    """ClaimAdjuster acting as an arbitrary operator id."""
    return build_user_headers(user_id, "ClaimAdjuster")


def make_project_contact_headers(project_id: str) -> dict:
    """For ProjectContact: X-User-ID is the id of the acting ConstructionProject."""
    return build_user_headers(project_id, "ProjectContact")


def make_loss_payee_headers(interest_id: str) -> dict:
    """For LossPayee: X-User-ID is the id of the acting NamedInsuredInterest."""
    return build_user_headers(interest_id, "LossPayee")
