"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use opaque operator identifiers: the server records X-User-ID
for segregation-of-duties comparisons but never matches it against any
entity's id (PRD §2.1), so shared constants are canonical. Per-user builders
exist for segregation-of-duties scenarios where the compared identifiers
must be controlled (preparer vs reviewer, drafter vs signer).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for all four (opaque) roles.
TEST_USERS = {
    "claims_examiner_headers": build_user_headers("examiner-1", "ClaimsExaminer"),
    "actuarial_analyst_headers": build_user_headers("analyst-1", "ActuarialAnalyst"),
    "peer_reviewer_headers": build_user_headers("reviewer-1", "PeerReviewer"),
    "appointed_actuary_headers": build_user_headers("aa-1", "AppointedActuary"),
}

# Anonymous pseudo-role (PRD §2.1): no valid authentication headers at all.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_claims_examiner_headers(user_id: str) -> dict:
    """ClaimsExaminer headers with a specific operator id."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_actuarial_analyst_headers(user_id: str) -> dict:
    """ActuarialAnalyst headers with a specific operator id. The id is recorded
    as a study's created_by_user_id, so segregation-of-duties tests must choose
    it deliberately."""
    return build_user_headers(user_id, "ActuarialAnalyst")


def make_peer_reviewer_headers(user_id: str) -> dict:
    """PeerReviewer headers with a specific operator id (recorded as
    reviewed_by_user_id on review)."""
    return build_user_headers(user_id, "PeerReviewer")


def make_appointed_actuary_headers(user_id: str) -> dict:
    """AppointedActuary headers with a specific operator id (recorded as
    created_by_user_id / signed_by_user_id on opinions)."""
    return build_user_headers(user_id, "AppointedActuary")
