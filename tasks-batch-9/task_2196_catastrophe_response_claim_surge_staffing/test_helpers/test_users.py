"""Pre-built role headers for every role in the PRD.

Identity binding differs by role. For `CatastropheManager`, `DeploymentCoordinator`,
`ClaimsExaminer` and `ComplianceOfficer`, `X-User-ID` is an opaque operator
identifier that is never compared to any entity's `id`, so the shared constants
below are always safe. For `Adjuster` and `VendorCoordinator`, `X-User-ID` is the
`id` of the acting `Adjuster` / `VendorFirm` row, so ownership-gated calls MUST use
``make_adjuster_headers(adjuster["id"])`` / ``make_vendor_coordinator_headers(firm["id"])``.
"""
from prd_bench_local_runner.testing import build_user_headers

CATASTROPHE_MANAGER = "CatastropheManager"
DEPLOYMENT_COORDINATOR = "DeploymentCoordinator"
CLAIMS_EXAMINER = "ClaimsExaminer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
ADJUSTER = "Adjuster"
VENDOR_COORDINATOR = "VendorCoordinator"

# Stable opaque operator identifiers. Distinct per role so segregation-of-duties
# scenarios can pick two identities that are guaranteed to differ.
CM_USER_ID = "cm_1"
CM_USER_ID_ALT = "cm_2"
DC_USER_ID = "dc_1"
DC_USER_ID_ALT = "dc_2"
CE_USER_ID = "ce_1"
CE_USER_ID_ALT = "ce_2"
CO_USER_ID = "co_1"
CO_USER_ID_ALT = "co_2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "catastrophe_manager_headers": build_user_headers(CM_USER_ID, CATASTROPHE_MANAGER),
    "catastrophe_manager_alt_headers": build_user_headers(CM_USER_ID_ALT, CATASTROPHE_MANAGER),
    "deployment_coordinator_headers": build_user_headers(DC_USER_ID, DEPLOYMENT_COORDINATOR),
    "deployment_coordinator_alt_headers": build_user_headers(DC_USER_ID_ALT, DEPLOYMENT_COORDINATOR),
    "claims_examiner_headers": build_user_headers(CE_USER_ID, CLAIMS_EXAMINER),
    "claims_examiner_alt_headers": build_user_headers(CE_USER_ID_ALT, CLAIMS_EXAMINER),
    "compliance_officer_headers": build_user_headers(CO_USER_ID, COMPLIANCE_OFFICER),
    "compliance_officer_alt_headers": build_user_headers(CO_USER_ID_ALT, COMPLIANCE_OFFICER),
    # Entity-backed roles — these shared constants are for tests that never reach
    # an ownership check (missing-header, unknown-role, 404 and role-permission
    # scenarios). Ownership-gated calls must use the builders below.
    "adjuster_headers": build_user_headers("adj-not-a-real-row", ADJUSTER),
    "vendor_coordinator_headers": build_user_headers("vf-not-a-real-row", VENDOR_COORDINATOR),
}


def make_catastrophe_manager_headers(user_id: str = CM_USER_ID) -> dict:
    """Opaque operator identity acting as CatastropheManager."""
    return build_user_headers(user_id, CATASTROPHE_MANAGER)


def make_deployment_coordinator_headers(user_id: str = DC_USER_ID) -> dict:
    """Opaque operator identity acting as DeploymentCoordinator."""
    return build_user_headers(user_id, DEPLOYMENT_COORDINATOR)


def make_claims_examiner_headers(user_id: str = CE_USER_ID) -> dict:
    """Opaque operator identity acting as ClaimsExaminer."""
    return build_user_headers(user_id, CLAIMS_EXAMINER)


def make_compliance_officer_headers(user_id: str = CO_USER_ID) -> dict:
    """Opaque operator identity acting as ComplianceOfficer."""
    return build_user_headers(user_id, COMPLIANCE_OFFICER)


def make_adjuster_headers(adjuster_id: str) -> dict:
    """Acting Adjuster identity: pass the real Adjuster row's `id` as X-User-ID."""
    return build_user_headers(adjuster_id, ADJUSTER)


def make_vendor_coordinator_headers(vendor_firm_id: str) -> dict:
    """Acting VendorCoordinator identity: pass the real VendorFirm row's `id`."""
    return build_user_headers(vendor_firm_id, VENDOR_COORDINATOR)


def headers_for_role(role: str, user_id: str = "generic-user-1") -> dict:
    """Headers for an arbitrary role string. Useful for role-permission matrices."""
    return build_user_headers(user_id, role)


def missing_role_headers(user_id: str = "generic-user-1") -> dict:
    """Headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def missing_user_id_headers(role: str = CATASTROPHE_MANAGER) -> dict:
    """Headers carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
