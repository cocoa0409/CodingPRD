"""Pre-built role headers for every role in the PRD.

`BrandAdmin` and `ComplianceIntegrator` carry an opaque operator identifier that
the server never compares to any entity's `id`, so the shared constants below are
the canonical form for those two roles. `Auditor`, `CalibrationReviewer` and
`Franchisee` are entity-backed: their `X-User-ID` must resolve to an existing row
of the backing entity, so ownership-gated calls MUST use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque roles, and for entity-backed roles
# only in tests that deliberately exercise an unresolvable acting identity.
TEST_USERS = {
    "brand_admin_headers": build_user_headers("ops-admin-1", "BrandAdmin"),
    "compliance_integrator_headers": build_user_headers("health-feed-1", "ComplianceIntegrator"),
    # Entity-backed roles: these identifiers do NOT resolve to any persisted row.
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "calibration_reviewer_headers": build_user_headers("test-reviewer-1", "CalibrationReviewer"),
    "franchisee_headers": build_user_headers("test-franchisee-1", "Franchisee"),
}


def make_brand_admin_headers(user_id: str = "ops-admin-1") -> dict:
    """For BrandAdmin, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "BrandAdmin")


def make_compliance_integrator_headers(user_id: str = "health-feed-1") -> dict:
    """For ComplianceIntegrator, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "ComplianceIntegrator")


def make_auditor_headers(user_id: str) -> dict:
    """For the Auditor role. Pass the acting Auditor record's `id`."""
    return build_user_headers(user_id, "Auditor")


def make_calibration_reviewer_headers(user_id: str) -> dict:
    """For the CalibrationReviewer role, backed by the same Auditor entity as the
    Auditor role. Pass the acting Auditor record's `id`."""
    return build_user_headers(user_id, "CalibrationReviewer")


def make_franchisee_headers(user_id: str) -> dict:
    """For the Franchisee role. Pass the acting Franchisee record's `id`."""
    return build_user_headers(user_id, "Franchisee")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix tests."""
    return build_user_headers(user_id, role)
