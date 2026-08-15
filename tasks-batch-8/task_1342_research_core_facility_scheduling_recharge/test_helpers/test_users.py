"""Pre-built role headers for every role in the PRD (§2.1).

FacilityAdmin / CoreStaff / FinanceOfficer are opaque operator roles: their
X-User-ID is not tied to any persisted entity, so shared constants are
canonical. Researcher / ExternalClient are entity-backed: X-User-ID must equal
the acting User's id, so per-instance builders are mandatory for any
ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — safe as shared constants.
    "admin_headers": build_user_headers("admin-1", "FacilityAdmin"),
    "staff_headers": build_user_headers("staff-1", "CoreStaff"),
    "staff2_headers": build_user_headers("staff-2", "CoreStaff"),
    "finance_headers": build_user_headers("fin-1", "FinanceOfficer"),
    # Entity-backed fallback constants — ONLY for tests that never exercise
    # ownership (e.g. 400-on-bad-payload). Never use for ownership-gated calls.
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
    "external_headers": build_user_headers("test-external-1", "ExternalClient"),
}


def make_researcher_headers(user_id: str) -> dict:
    """Researcher is entity-backed: pass the actual User.id as user_id."""
    return build_user_headers(user_id, "Researcher")


def make_external_client_headers(user_id: str) -> dict:
    """ExternalClient is entity-backed: pass the actual User.id as user_id."""
    return build_user_headers(user_id, "ExternalClient")


def make_finance_headers(operator_id: str) -> dict:
    """FinanceOfficer is opaque; a distinct operator id is needed for
    segregation-of-duties scenarios (e.g. approver id equal to developed_by)."""
    return build_user_headers(operator_id, "FinanceOfficer")


def make_staff_headers(operator_id: str) -> dict:
    """CoreStaff is opaque; distinct operator ids drive usage-log SoD."""
    return build_user_headers(operator_id, "CoreStaff")
