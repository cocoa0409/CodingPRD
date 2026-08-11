"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Coordinator, Veterinarian,
# ComplianceOfficer, Operator, Anonymous) whose X-User-ID is never compared to
# a persisted entity id, and for tests that do not exercise ownership.
# Customer is entity-backed: the shared constant is only a fallback for
# non-ownership tests (e.g., 403-by-role, 404-on-missing). Ownership-gated
# calls MUST use make_customer_headers() threaded with the real Customer.id.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
    "coordinator_headers": build_user_headers("coord-1", "Coordinator"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "operator_headers": build_user_headers("op-1", "Operator"),
}


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "Anonymous")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (own venues, bookings,
    payments, waivers, add-on requests, insurance certificates)."""
    return build_user_headers(user_id, "Customer")


def make_coordinator_headers(user_id: str = "coord-1") -> dict:
    """Coordinator is opaque; the id may be recorded as submitted_by_user_id
    on a Permit at submit time but is never matched to an entity id."""
    return build_user_headers(user_id, "Coordinator")


def make_veterinarian_headers(user_id: str = "vet-1") -> dict:
    """Veterinarian is opaque; the id is recorded nowhere and compared to nothing."""
    return build_user_headers(user_id, "Veterinarian")


def make_compliance_officer_headers(user_id: str = "officer-1") -> dict:
    """ComplianceOfficer is opaque; the id is recorded as decided_by_user_id
    on decided permits and drives segregation-of-duties comparisons."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_operator_headers(user_id: str = "op-1") -> dict:
    """Operator is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "Operator")
