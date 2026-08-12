"""Pre-built role headers for every role in the PRD (§2.1).

The Member role is entity-backed: X-User-ID must be the id of the acting Member
for any ownership-gated call. Operator roles carry opaque user identifiers, but
InsuranceSpecialist / BillingSpecialist identifiers are recorded on claims and
prior authorizations and compared by the segregation-of-duties rule (PRD §3.6),
so per-instance builders are provided for them as well.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for calls whose success does not depend on the exact
# caller identifier (no ownership gate, no segregation-of-duties comparison).
TEST_USERS = {
    "care_coordinator_headers": build_user_headers("cc-1", "CareCoordinator"),
    "insurance_specialist_headers": build_user_headers("ins-1", "InsuranceSpecialist"),
    "billing_specialist_headers": build_user_headers("bill-1", "BillingSpecialist"),
    "warehouse_operator_headers": build_user_headers("wh-1", "WarehouseOperator"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallback for the entity-backed Member role in non-ownership contexts only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: pass the actual Member.id for ownership-gated calls."""
    return build_user_headers(user_id, "Member")


def make_care_coordinator_headers(user_id: str = "cc-1") -> dict:
    return build_user_headers(user_id, "CareCoordinator")


def make_insurance_specialist_headers(user_id: str = "ins-1") -> dict:
    """Use a distinct id when the call is segregation-of-duties sensitive."""
    return build_user_headers(user_id, "InsuranceSpecialist")


def make_billing_specialist_headers(user_id: str = "bill-1") -> dict:
    """Use a distinct id when the call is segregation-of-duties sensitive."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_warehouse_operator_headers(user_id: str = "wh-1") -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
