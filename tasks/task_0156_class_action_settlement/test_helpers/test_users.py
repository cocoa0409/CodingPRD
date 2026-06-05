"""Pre-built role headers for every role in the PRD (§2.1).

Five roles carry an opaque identity (SettlementAdmin, FundController,
ClaimsReviewer, ClaimsAdministrator, Court): their X-User-ID is an opaque
operator id not tied to any stored row, so the shared constant is canonical.

The Claimant role is entity-backed by ClassMember: its X-User-ID must equal
the acting member's id. Use make_claimant_headers(member_id) whenever the call
is ownership-gated (self-serve file-claim, objection withdraw).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "settlement_admin_headers": build_user_headers("admin-1", "SettlementAdmin"),
    "fund_controller_headers": build_user_headers("controller-1", "FundController"),
    "claims_reviewer_headers": build_user_headers("reviewer-1", "ClaimsReviewer"),
    "claims_administrator_headers": build_user_headers("administrator-1", "ClaimsAdministrator"),
    "court_headers": build_user_headers("court-1", "Court"),
    # Claimant entity_backed shared fallback — only for non-ownership tests.
    "claimant_headers": build_user_headers("claimant-fallback", "Claimant"),
}


def make_settlement_admin_headers(user_id: str) -> dict:
    """SettlementAdmin (opaque). Distinct opaque ids let segregation-of-duties
    and clock-driving be attributed to specific operators when a test needs it."""
    return build_user_headers(user_id, "SettlementAdmin")


def make_fund_controller_headers(user_id: str) -> dict:
    """FundController (opaque). Used to vary the posting operator id for the
    segregation-of-duties comparison against the validating reviewer."""
    return build_user_headers(user_id, "FundController")


def make_claims_reviewer_headers(user_id: str) -> dict:
    """ClaimsReviewer (opaque). The server records this id at claim validation;
    vary it to drive the segregation-of-duties rule."""
    return build_user_headers(user_id, "ClaimsReviewer")


def make_claims_administrator_headers(user_id: str) -> dict:
    """ClaimsAdministrator (opaque)."""
    return build_user_headers(user_id, "ClaimsAdministrator")


def make_court_headers(user_id: str) -> dict:
    """Court (opaque)."""
    return build_user_headers(user_id, "Court")


def make_claimant_headers(member_id: str) -> dict:
    """Claimant (entity_backed:ClassMember). Pass the acting ClassMember.id as
    user_id whenever the call is ownership-gated (self-serve file-claim, cure,
    objection withdraw)."""
    return build_user_headers(member_id, "Claimant")
