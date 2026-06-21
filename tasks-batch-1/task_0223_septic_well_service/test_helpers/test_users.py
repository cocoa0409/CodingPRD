"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Dispatcher and ComplianceOfficer are opaque operator identities: the shared
#    constant is the canonical form (X-User-ID is never matched to an entity id).
#  - FieldTech (entity_backed:Technician) and Customer (entity_backed:Account)
#    shared constants are fallbacks for tests that do NOT exercise ownership
#    (e.g. 403/404 negative tests). Ownership-gated calls MUST use the per-instance
#    builders below with the real entity id.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "field_tech_headers": build_user_headers("test-fieldtech-1", "FieldTech"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builders — required for every entity_backed role.

def make_field_tech_headers(technician_id: str) -> dict:
    """For FieldTech (entity_backed:Technician). Pass the acting Technician.id as
    X-User-ID whenever the call is ownership-gated (start/complete own work order)."""
    return build_user_headers(technician_id, "FieldTech")


def make_customer_headers(account_id: str) -> dict:
    """For Customer (entity_backed:Account). Pass the acting Account.id as
    X-User-ID whenever the call is ownership-gated on the account."""
    return build_user_headers(account_id, "Customer")
