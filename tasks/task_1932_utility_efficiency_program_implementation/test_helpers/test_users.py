"""Pre-built role headers for every role in the PRD (section 2.1).

ProgramManager is an opaque role: its X-User-ID is never compared to a
resource id, so the shared constant is canonical.

Contractor / Inspector / Customer are entity-backed roles: ownership checks
compare X-User-ID to the referenced entity's id, so ownership-gated calls
MUST use the per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque ProgramManager and for tests whose
# success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    # Entity-backed fallbacks: use ONLY for non-ownership calls (e.g. RBAC
    # denial tests where any contractor identity suffices).
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_program_manager_headers(user_id: str = "test-pm-1") -> dict:
    """ProgramManager (opaque identity)."""
    return build_user_headers(user_id, "ProgramManager")


def make_contractor_headers(user_id: str) -> dict:
    """Contractor (entity-backed). Pass the actual Contractor.id as user_id
    whenever the call is ownership-gated (lead accept, work-order actions)."""
    return build_user_headers(user_id, "Contractor")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector (entity-backed). Pass the actual Inspector.id as user_id
    whenever the call is ownership-gated (inspection create/record)."""
    return build_user_headers(user_id, "Inspector")


def make_customer_headers(user_id: str) -> dict:
    """Customer (entity-backed). Pass the actual Customer.id as user_id."""
    return build_user_headers(user_id, "Customer")
