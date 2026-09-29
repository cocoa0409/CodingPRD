"""Pre-built request headers for each role, plus per-agency liaison builders.

Five roles carry an opaque identity, so a shared constant header dict is safe
for them. AgencyLiaison is different: X-User-ID must be the id of the acting
Agency, so liaison headers must always be built from a captured agency id with
make_agency_liaison_headers().
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_LIAISON,
    ROLE_GIS_ANALYST,
    ROLE_PERMIT_COORDINATOR,
    ROLE_PROVISIONING_OFFICER,
    ROLE_QC_CERTIFIER,
    ROLE_SYSTEM_ADMIN,
)

# --- Canonical opaque operator identifiers ----------------------------------
SYSADMIN_USER_ID = "sysadmin-1"
ANALYST_USER_ID = "analyst-1"
QC_USER_ID = "qc-1"
PROV_USER_ID = "prov-1"
PERMIT_USER_ID = "permit-1"

# Secondary operators, for segregation-of-duties scenarios.
SYSADMIN_2_USER_ID = "sysadmin-2"
ANALYST_2_USER_ID = "analyst-2"
QC_2_USER_ID = "qc-2"
PROV_2_USER_ID = "prov-2"
PERMIT_2_USER_ID = "permit-2"

# --- Pre-built headers for the five opaque roles ----------------------------
SYSADMIN_HEADERS = build_user_headers(SYSADMIN_USER_ID, ROLE_SYSTEM_ADMIN)
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, ROLE_GIS_ANALYST)
QC_HEADERS = build_user_headers(QC_USER_ID, ROLE_QC_CERTIFIER)
PROV_HEADERS = build_user_headers(PROV_USER_ID, ROLE_PROVISIONING_OFFICER)
PERMIT_HEADERS = build_user_headers(PERMIT_USER_ID, ROLE_PERMIT_COORDINATOR)

SYSADMIN_2_HEADERS = build_user_headers(SYSADMIN_2_USER_ID, ROLE_SYSTEM_ADMIN)
ANALYST_2_HEADERS = build_user_headers(ANALYST_2_USER_ID, ROLE_GIS_ANALYST)
QC_2_HEADERS = build_user_headers(QC_2_USER_ID, ROLE_QC_CERTIFIER)
PROV_2_HEADERS = build_user_headers(PROV_2_USER_ID, ROLE_PROVISIONING_OFFICER)
PERMIT_2_HEADERS = build_user_headers(PERMIT_2_USER_ID, ROLE_PERMIT_COORDINATOR)


def make_agency_liaison_headers(agency_id: str) -> Dict[str, str]:
    """Headers for an AgencyLiaison acting on behalf of ``agency_id``.

    X-User-ID must be the acting Agency's own id; ownership checks compare a
    resource's agency-referencing field against it.
    """
    return build_user_headers(agency_id, ROLE_AGENCY_LIAISON)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user-id/role pairing, for role-matrix and identity tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but an empty X-User-ID."""
    return {"X-User-Role": role, "X-User-ID": "", "Content-Type": "application/json"}


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role and no X-User-ID header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# Headers for every role, keyed by role name, for role-matrix sweeps. The
# AgencyLiaison entry is deliberately absent because its identity is entity
# backed and must be built per agency.
OPAQUE_ROLE_HEADERS = {
    ROLE_SYSTEM_ADMIN: SYSADMIN_HEADERS,
    ROLE_GIS_ANALYST: ANALYST_HEADERS,
    ROLE_QC_CERTIFIER: QC_HEADERS,
    ROLE_PROVISIONING_OFFICER: PROV_HEADERS,
    ROLE_PERMIT_COORDINATOR: PERMIT_HEADERS,
}
