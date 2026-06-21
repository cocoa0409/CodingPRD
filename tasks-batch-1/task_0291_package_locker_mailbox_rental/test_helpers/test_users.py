"""Pre-built role headers for every role in the PRD.

FacilityOperator and ComplianceOfficer are opaque roles: their X-User-ID is an
operator/reviewer identifier never matched to a stored row, so the shared
constant is the canonical form. Customer is entity-backed: ownership checks
compare X-User-ID to the Customer's id, so ownership-gated calls MUST use the
per-instance builder make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - FacilityOperator / ComplianceOfficer: opaque, canonical form.
# - Customer: fallback ONLY for tests that do not exercise ownership
#   (e.g. unknown-role / missing-resource paths). Never use for ownership-gated
#   calls — use make_customer_headers(customer_id) instead.
TEST_USERS = {
    "facility_operator_headers": build_user_headers("op-1", "FacilityOperator"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_facility_operator_headers(user_id: str = "op-1") -> dict:
    """FacilityOperator is opaque; user_id is logged but never matched."""
    return build_user_headers(user_id, "FacilityOperator")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    """ComplianceOfficer is opaque; user_id is logged but never matched."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_role_headers(role: str, user_id: str) -> dict:
    """Generic helper: build headers for an arbitrary (possibly unknown) role.
    Used by authentication tests that deliberately send an undeclared role."""
    return build_user_headers(user_id, role)
