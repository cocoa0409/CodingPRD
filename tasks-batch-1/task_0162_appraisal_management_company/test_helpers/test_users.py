"""Pre-built role headers for every role in the AMC API (PRD §2.1).

Three roles use an opaque identity model: AMCCoordinator, ComplianceReviewer,
and PlatformAdmin. Their X-User-ID is an operator identifier never compared to a
persisted entity, so the shared constants below are always safe for them.

Two roles are entity-backed and ownership-gated:
  - Appraiser: X-User-ID must equal the acting Appraiser's id. Accept, decline,
    and report-submit compare the assignment's appraiser_id to X-User-ID.
  - LenderUser: X-User-ID must equal the acting Lender's id.
For these, fixtures MUST call the per-instance builders below with the real
entity id; the shared TEST_USERS constants are only valid for tests whose
success does not depend on ownership (e.g. firewall/RBAC denials).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "coordinator_headers": build_user_headers("coordinator-1", "AMCCoordinator"),
    "compliance_reviewer_headers": build_user_headers("reviewer-1", "ComplianceReviewer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only
    # (RBAC/firewall denials where the request never reaches an ownership check).
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "lender_user_headers": build_user_headers("lender-1", "LenderUser"),
}


def make_appraiser_headers(appraiser_id: str) -> dict:
    """For the Appraiser role (entity_backed:Appraiser). Pass the real Appraiser.id
    whenever the call is ownership-gated (accept/decline/submit report)."""
    return build_user_headers(appraiser_id, "Appraiser")


def make_lender_user_headers(lender_id: str) -> dict:
    """For the LenderUser role (entity_backed:Lender). Pass the real Lender.id
    whenever the call is ownership-gated (place order / reconsideration on own lender)."""
    return build_user_headers(lender_id, "LenderUser")


def headers_for(role: str, user_id: str) -> dict:
    """Build auth headers for an arbitrary (role, X-User-ID) pair."""
    return build_user_headers(user_id, role)
