"""Pre-built role headers for every role in the PRD (§2.1).

`Physician` is entity-backed: X-User-ID must be the acting Physician's id, so
ownership-gated calls MUST use make_physician_headers(physician["id"]).
`BoardAdmin` and `ComplianceOfficer` are opaque: the shared constants are
canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Physician tests whose
# success does not depend on owning the subject resource (e.g. 400/404 paths).
TEST_USERS = {
    "board_admin_headers": build_user_headers("admin-1", "BoardAdmin"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    # Fallback only for non-ownership Physician calls.
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
}


def make_physician_headers(user_id: str) -> dict:
    """Physician is entity-backed: pass the actual Physician.id as user_id
    whenever the call is ownership-gated (own offers, votes, disclosures,
    exit valuation, assessments, own-motion sponsorship)."""
    return build_user_headers(user_id, "Physician")


def make_board_admin_headers(user_id: str) -> dict:
    """BoardAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "BoardAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque; the id is recorded as reviewed_by."""
    return build_user_headers(user_id, "ComplianceOfficer")
