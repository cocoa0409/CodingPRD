"""Pre-built role headers for every role in the PRD.

Per PRD §2.1: PrincipalRep and VendorRep are entity-backed — X-User-ID must
equal the acting Principal/Vendor id whenever the call is ownership-gated.
The shared TEST_USERS constants for those two roles are only safe for tests
whose outcome does not depend on ownership; ownership-gated flows MUST use
make_principal_rep_headers(principal_id) / make_vendor_rep_headers(vendor_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    "agency_ops_headers": build_user_headers("ops-1", "AgencyOps"),
    "agency_finance_headers": build_user_headers("fin-1", "AgencyFinance"),
    "port_authority_headers": build_user_headers("test-port-1", "PortAuthority"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "principal_rep_headers": build_user_headers("test-principal-1", "PrincipalRep"),
    "vendor_rep_headers": build_user_headers("test-vendor-1", "VendorRep"),
    "crewing_agent_headers": build_user_headers("test-crew-1", "CrewingAgent"),
    "husbandry_officer_headers": build_user_headers("test-husbandry-1", "HusbandryOfficer"),
}


def make_agency_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_agency_ops_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "AgencyOps")


def make_agency_finance_headers(user_id: str = "fin-1") -> dict:
    return build_user_headers(user_id, "AgencyFinance")


def make_port_authority_headers(user_id: str = "test-port-1") -> dict:
    return build_user_headers(user_id, "PortAuthority")


def make_principal_rep_headers(user_id: str) -> dict:
    """For PrincipalRep (entity_backed:Principal). Pass the actual Principal.id
    whenever the call is ownership-gated (disputes, advances, escalate)."""
    return build_user_headers(user_id, "PrincipalRep")


def make_vendor_rep_headers(user_id: str) -> dict:
    """For VendorRep (entity_backed:Vendor). Pass the actual Vendor.id
    whenever the call is ownership-gated (PO acknowledge/deliver/invoice,
    non-PILOT service-order confirm)."""
    return build_user_headers(user_id, "VendorRep")


def make_crewing_agent_headers(user_id: str = "test-crew-1") -> dict:
    return build_user_headers(user_id, "CrewingAgent")


def make_husbandry_officer_headers(user_id: str = "test-husbandry-1") -> dict:
    return build_user_headers(user_id, "HusbandryOfficer")
