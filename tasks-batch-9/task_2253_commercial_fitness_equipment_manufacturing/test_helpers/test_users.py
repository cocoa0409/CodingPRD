"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque operator identifier in X-User-ID. Two roles are
resource-backed: a FacilityManager's X-User-ID is the acting Facility's id and
a ServicePartnerTech's X-User-ID is the acting ServicePartner's id, so those
two always need a per-instance builder rather than a shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used throughout the suite. The two compliance-officer
# identities exist because certifying a firmware pairing requires an officer
# different from the submitter.
PRODUCT_ENGINEER_USER_ID = "pe-01"
PRODUCT_ENGINEER_ALT_USER_ID = "pe-02"
COMPLIANCE_OFFICER_USER_ID = "co-01"
COMPLIANCE_OFFICER_ALT_USER_ID = "co-02"
ORDER_PLANNER_USER_ID = "op-01"
SERVICE_OPS_ADMIN_USER_ID = "soa-01"

TEST_USERS = {
    # Opaque operator identities — the shared constant is the canonical form.
    "product_engineer_headers": build_user_headers(
        PRODUCT_ENGINEER_USER_ID, "ProductEngineer"
    ),
    "product_engineer_alt_headers": build_user_headers(
        PRODUCT_ENGINEER_ALT_USER_ID, "ProductEngineer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_alt_headers": build_user_headers(
        COMPLIANCE_OFFICER_ALT_USER_ID, "ComplianceOfficer"
    ),
    "order_planner_headers": build_user_headers(ORDER_PLANNER_USER_ID, "OrderPlanner"),
    "service_ops_admin_headers": build_user_headers(
        SERVICE_OPS_ADMIN_USER_ID, "ServiceOpsAdmin"
    ),
    # Resource-backed identities — these shared constants are only safe for
    # tests that never reach an ownership check (authentication probes, schema
    # probes, role-permission probes).
    "facility_manager_headers": build_user_headers(
        "unbound-facility-manager", "FacilityManager"
    ),
    "service_partner_tech_headers": build_user_headers(
        "unbound-service-partner-tech", "ServicePartnerTech"
    ),
}


def make_product_engineer_headers(user_id: str) -> dict:
    """ProductEngineer with an explicit operator id (stamped into
    submitted_by_user_id on a firmware certification)."""
    return build_user_headers(user_id, "ProductEngineer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with an explicit operator id (the counterparty for the
    segregation-of-duties check on certify and reject)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_order_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OrderPlanner")


def make_service_ops_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceOpsAdmin")


def make_facility_manager_headers(facility_id: str) -> dict:
    """FacilityManager headers. X-User-ID must be the acting Facility's id;
    pass the real facility id on every ownership-gated call."""
    return build_user_headers(facility_id, "FacilityManager")


def make_service_partner_tech_headers(service_partner_id: str) -> dict:
    """ServicePartnerTech headers. X-User-ID must be the acting
    ServicePartner's id; pass the real partner id on every ownership-gated
    call."""
    return build_user_headers(service_partner_id, "ServicePartnerTech")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary header pair — used for unknown-role and empty-header probes."""
    return build_user_headers(user_id, role)


#: Every role name the system recognises, spelled exactly as the PRD spells it.
ALL_ROLE_NAMES = [
    "ProductEngineer",
    "ComplianceOfficer",
    "OrderPlanner",
    "FacilityManager",
    "ServicePartnerTech",
    "ServiceOpsAdmin",
]
