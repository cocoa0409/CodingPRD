"""Pre-built role headers for every role in the PRD (§2.1).

The four staff roles are opaque operator identifiers; the Customer role is
entity-backed: X-User-ID must equal the acting CustomerAccount's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque staff roles and for tests that do not
# exercise ownership. For ownership-gated Customer calls, ALWAYS use
# make_customer_headers(account["id"]) instead of this fallback.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "csr_headers": build_user_headers("csr_1", "CustomerServiceRep"),
    "specialist_headers": build_user_headers("es_1", "EligibilitySpecialist"),
    "admin_headers": build_user_headers("admin_1", "ProgramAdmin"),
    "fieldcrew_headers": build_user_headers("crew_1", "FieldCrew"),
}

# A headers dict with no auth headers at all (for the unauthenticated case).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual CustomerAccount.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_csr_headers(user_id: str) -> dict:
    """CustomerServiceRep with a specific opaque operator id (segregation-of-
    duties tests need to control the acting X-User-ID)."""
    return build_user_headers(user_id, "CustomerServiceRep")


def make_specialist_headers(user_id: str) -> dict:
    """EligibilitySpecialist with a specific opaque operator id."""
    return build_user_headers(user_id, "EligibilitySpecialist")


def make_admin_headers(user_id: str) -> dict:
    """ProgramAdmin with a specific opaque operator id."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_fieldcrew_headers(user_id: str) -> dict:
    """FieldCrew with a specific opaque operator id."""
    return build_user_headers(user_id, "FieldCrew")
