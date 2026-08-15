"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. ClientContact is entity-backed: use make_client_contact_headers()
# with the real client id whenever a call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "reviewer_headers": build_user_headers("cr-1", "CertificationReviewer"),
    "supervisor_headers": build_user_headers("sup-1", "FieldSupervisor"),
    "officer_headers": build_user_headers("co-1", "CertificateOfficer"),
    # Fallback only for non-ownership contexts; real calls must thread the id.
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
}


def make_client_contact_headers(client_id: str) -> dict:
    """ClientContact is entity-backed: X-User-ID must equal the AgencyClient id
    for every ownership-gated call."""
    return build_user_headers(client_id, "ClientContact")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_account_manager_headers(user_id: str = "am-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_reviewer_headers(user_id: str = "cr-1") -> dict:
    return build_user_headers(user_id, "CertificationReviewer")


def make_supervisor_headers(user_id: str) -> dict:
    """FieldSupervisor is opaque but assignment-scoped: pass the same id that
    the visit/window was assigned to (inspector_user_id / assigned_supervisor_id)."""
    return build_user_headers(user_id, "FieldSupervisor")


def make_officer_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "CertificateOfficer")
