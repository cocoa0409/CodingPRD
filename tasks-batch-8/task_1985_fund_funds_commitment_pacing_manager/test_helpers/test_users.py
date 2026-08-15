"""Pre-built role headers for every role in the PRD (§2.1).

CIO and ComplianceOfficer are opaque roles: X-User-ID is not resolved against
any entity, so a shared constant header is canonical.

Analyst, InvestmentCommittee, and OperationsAnalyst are entity-backed roles:
X-User-ID must equal the id of a StaffUser row whose staff_role matches.
Fixtures MUST call the per-instance builders below with the StaffUser id they
created; the shared constants for those roles are placeholders usable only
where ownership is not exercised (e.g., 401/404 tests) — but because the role
IS entity-backed, an unresolvable id would fail authentication, so prefer the
builders in every case that hits a real endpoint.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants for the two opaque roles (canonical form).
TEST_USERS = {
    "cio_headers": build_user_headers("test-cio-1", "CIO"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Entity-backed placeholders — DO NOT use for ownership-gated or
    # authenticated calls; these ids do not resolve to StaffUser rows.
    # They exist solely so tests can reference a consistent shape.
    "analyst_headers": build_user_headers("test-analyst-1", "Analyst"),
    "ic_headers": build_user_headers("test-ic-1", "InvestmentCommittee"),
    "ops_headers": build_user_headers("test-ops-1", "OperationsAnalyst"),
}


def make_analyst_headers(staff_user_id: str) -> dict:
    """Analyst is entity_backed:StaffUser(staff_role=ANALYST). Pass the StaffUser.id."""
    return build_user_headers(staff_user_id, "Analyst")


def make_ic_headers(staff_user_id: str) -> dict:
    """InvestmentCommittee is entity_backed:StaffUser(staff_role=IC_MEMBER)."""
    return build_user_headers(staff_user_id, "InvestmentCommittee")


def make_ops_headers(staff_user_id: str) -> dict:
    """OperationsAnalyst is entity_backed:StaffUser(staff_role=OPS_ANALYST)."""
    return build_user_headers(staff_user_id, "OperationsAnalyst")


def make_cio_headers(user_id: str = "test-cio-1") -> dict:
    """CIO is opaque; X-User-ID is not resolved against any entity."""
    return build_user_headers(user_id, "CIO")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer is opaque; X-User-ID is not resolved against any entity."""
    return build_user_headers(user_id, "ComplianceOfficer")
