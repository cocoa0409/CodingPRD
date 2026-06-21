"""Pre-built role headers for every role in the PRD (PRD §2.1).

Two of the five roles are entity-backed (Applicant, Attorney) — for those, callers
MUST use the per-instance builders `make_applicant_headers(applicant_id)` /
`make_attorney_headers(attorney_id)` whenever the call is ownership-gated, because
the shared `TEST_USERS` constant carries a fake user-id string that never equals any
real entity's UUID. The opaque roles (Anonymous, Officer, FieldOfficeAdmin) use the
shared constants safely.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": {},  # the two register endpoints accept no auth
    "officer_headers": build_user_headers("test-officer-1", "Officer"),
    "field_office_admin_headers": build_user_headers("test-admin-1", "FieldOfficeAdmin"),
    # Entity-backed roles — shared constants are a fallback for non-ownership tests
    # (e.g., 400/401/403/404 paths where the resource does not exist).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """Headers for the Applicant role bound to a specific Applicant.id."""
    return build_user_headers(applicant_id, "Applicant")


def make_attorney_headers(attorney_id: str) -> dict:
    """Headers for the Attorney role bound to a specific Attorney.id."""
    return build_user_headers(attorney_id, "Attorney")


def make_officer_headers(officer_id: str) -> dict:
    """Headers for the Officer role, bound to the opaque officer-id the server
    minted at filing time (Case.assigned_officer_id)."""
    return build_user_headers(officer_id, "Officer")


def make_admin_headers(admin_id: str = "test-admin-1") -> dict:
    """Headers for the FieldOfficeAdmin role."""
    return build_user_headers(admin_id, "FieldOfficeAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
