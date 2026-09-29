"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATORS

# Shared constants — safe for the three opaque roles (CEManager, BiomedTech,
# SecurityOfficer), whose X-User-ID is never compared to an entity id, and for
# tests that never exercise ownership.
TEST_USERS = {
    "ce_manager_headers": build_user_headers(OPERATORS["manager"], "CEManager"),
    "biomed_tech_headers": build_user_headers(OPERATORS["tech_alpha"], "BiomedTech"),
    "biomed_tech_peer_headers": build_user_headers(OPERATORS["tech_bravo"], "BiomedTech"),
    "security_officer_headers": build_user_headers(OPERATORS["security"], "SecurityOfficer"),
    # entity_backed roles: these shared constants are fallbacks for tests that do
    # NOT depend on the caller owning the subject resource.
    "dept_steward_headers": build_user_headers("test-dept-steward-1", "DeptSteward"),
    "vendor_rep_headers": build_user_headers("test-vendor-rep-1", "VendorRep"),
}

# Headers with no auth information at all — used to prove the §2.1 header rule.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_ce_manager_headers(user_id: str = OPERATORS["manager"]) -> dict:
    """CEManager is opaque; the id is recorded but never resolved."""
    return build_user_headers(user_id, "CEManager")


def make_biomed_tech_headers(user_id: str = OPERATORS["tech_alpha"]) -> dict:
    """BiomedTech is opaque; distinct ids matter only for segregation of duties."""
    return build_user_headers(user_id, "BiomedTech")


def make_security_officer_headers(user_id: str = OPERATORS["security"]) -> dict:
    """SecurityOfficer is opaque."""
    return build_user_headers(user_id, "SecurityOfficer")


def make_dept_steward_headers(department_id: str) -> dict:
    """DeptSteward's X-User-ID is the acting Department's id — always pass the real id."""
    return build_user_headers(department_id, "DeptSteward")


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """VendorRep's X-User-ID is the acting Vendor's id — always pass the real id."""
    return build_user_headers(vendor_id, "VendorRep")
