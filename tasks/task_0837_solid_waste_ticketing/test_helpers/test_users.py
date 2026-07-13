"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "facility_admin_headers": build_user_headers("adm1", "FacilityAdmin"),
    "gate_operator_headers": build_user_headers("op1", "GateOperator"),
    "environmental_officer_headers": build_user_headers("eo1", "EnvironmentalOfficer"),
    "billing_clerk_headers": build_user_headers("bc1", "BillingClerk"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "hauler_headers": build_user_headers("hauler-fallback", "Hauler"),
}


# Per-instance builders. FacilityAdmin/GateOperator/EnvironmentalOfficer/BillingClerk are
# opaque, but their X-User-ID is semantically meaningful (e.g. GateOperator segregation of
# duties compares posting id vs inspected_by), so callers thread explicit ids.
def make_facility_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacilityAdmin")


def make_gate_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GateOperator")


def make_environmental_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_hauler_headers(user_id: str) -> dict:
    """For Hauler (entity_backed:HaulerAccount). Pass the acting HaulerAccount.id as user_id
    whenever the call is ownership-gated (manifest create/submit, payment create)."""
    return build_user_headers(user_id, "Hauler")
