"""Actor headers for the six declared roles.

Five roles carry an opaque caller identifier. The sixth, ``FieldTechnician``, is
entity backed: the ``X-User-ID`` header of a technician must be the identifier of
the ``VerificationCrew`` row the technician acts on, so technician headers can
only be built once a crew exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Stable opaque caller identifiers for the five non entity backed roles.
TEST_USERS = {
    "admin": "admin-1",
    "analyst": "analyst-1",
    "officer": "officer-1",
    "csr": "csr-1",
    "contractor": "contractor-1",
}

ADMIN_USER_ID = TEST_USERS["admin"]
ANALYST_USER_ID = TEST_USERS["analyst"]
OFFICER_USER_ID = TEST_USERS["officer"]
CSR_USER_ID = TEST_USERS["csr"]
CONTRACTOR_USER_ID = TEST_USERS["contractor"]

#: A second officer identity, for segregation of duties scenarios.
SECOND_OFFICER_USER_ID = "officer-2"
#: A second analyst identity, for segregation of duties scenarios.
SECOND_ANALYST_USER_ID = "analyst-2"


def make_program_administrator_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a ProgramAdministrator caller."""
    return build_user_headers(user_id, Role.PROGRAM_ADMINISTRATOR)


def make_inventory_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers for an InventoryAnalyst caller."""
    return build_user_headers(user_id, Role.INVENTORY_ANALYST)


def make_compliance_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for a ComplianceOfficer caller."""
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def make_customer_representative_headers(user_id: str = CSR_USER_ID) -> Dict[str, str]:
    """Headers for a CustomerRepresentative caller."""
    return build_user_headers(user_id, Role.CUSTOMER_REPRESENTATIVE)


def make_replacement_contractor_headers(
    user_id: str = CONTRACTOR_USER_ID,
) -> Dict[str, str]:
    """Headers for a ReplacementContractor caller."""
    return build_user_headers(user_id, Role.REPLACEMENT_CONTRACTOR)


def make_field_technician_headers(crew_id: str) -> Dict[str, str]:
    """Headers for a FieldTechnician acting as the crew identified by ``crew_id``."""
    return build_user_headers(crew_id, Role.FIELD_TECHNICIAN)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


#: Pre-built headers for the five opaque roles.
ADMIN_HEADERS = make_program_administrator_headers()
ANALYST_HEADERS = make_inventory_analyst_headers()
OFFICER_HEADERS = make_compliance_officer_headers()
CSR_HEADERS = make_customer_representative_headers()
CONTRACTOR_HEADERS = make_replacement_contractor_headers()

#: The default identifier used for each role when no override is supplied.
DEFAULT_USER_ID_BY_ROLE = {
    Role.PROGRAM_ADMINISTRATOR: ADMIN_USER_ID,
    Role.INVENTORY_ANALYST: ANALYST_USER_ID,
    Role.COMPLIANCE_OFFICER: OFFICER_USER_ID,
    Role.CUSTOMER_REPRESENTATIVE: CSR_USER_ID,
    Role.REPLACEMENT_CONTRACTOR: CONTRACTOR_USER_ID,
}


def headers_for_role(role: str, crew_id: str = "") -> Dict[str, str]:
    """Headers for ``role``, threading ``crew_id`` when the role is entity backed."""
    if role == Role.FIELD_TECHNICIAN:
        if not crew_id:
            raise ValueError("FieldTechnician headers require a crew identifier")
        return make_field_technician_headers(crew_id)
    return build_user_headers(DEFAULT_USER_ID_BY_ROLE[role], role)
