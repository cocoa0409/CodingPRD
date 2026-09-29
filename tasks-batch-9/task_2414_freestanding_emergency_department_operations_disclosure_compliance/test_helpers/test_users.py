"""Pre-built role headers for the seven roles the PRD declares.

PRD 2.1 is explicit that "None of the seven roles is backed by a persisted
entity" and that ``X-User-ID`` is always "an opaque operator identifier": the
server never resolves it against a stored row's ``id``.  Two controls
nevertheless read it, because PRD 2.9 compares the acting ``X-User-ID`` against
a *stored operator identifier* -- the template's ``published_by_user_id`` when a
signage attestation is filed, and the encounter's ``registered_by_user_id`` when
an emergent waiver is recorded.  Those two controls are why this module exposes
per-operator builders alongside the shared header constants: a test that must
put the same human behind two acts, or two different humans behind one act,
binds the id explicitly.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers.  ADMIN_USER_ID publishes templates, so a
# signage attestation filed by CO_USER_ID clears the segregation-of-duties
# control by construction; SECOND_CLERK_USER_ID exists so an emergent waiver can
# be recorded by somebody other than the registering clerk.
ADMIN_USER_ID = "admin-1"
SECOND_ADMIN_USER_ID = "admin-2"
CO_USER_ID = "co-1"
SECOND_CO_USER_ID = "co-2"
CLERK_USER_ID = "clerk-1"
SECOND_CLERK_USER_ID = "clerk-2"
PHYSICIAN_USER_ID = "doc-1"
COORDINATOR_USER_ID = "coord-1"
PAYER_USER_ID = "payer-1"
IDRE_USER_ID = "idre-1"

ROLE_FACILITY_ADMINISTRATOR = "FacilityAdministrator"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_REGISTRATION_CLERK = "RegistrationClerk"
ROLE_EMERGENCY_PHYSICIAN = "EmergencyPhysician"
ROLE_HOSPITAL_TRANSFER_COORDINATOR = "HospitalTransferCoordinator"
ROLE_PAYER_REPRESENTATIVE = "PayerRepresentative"
ROLE_IDR_ENTITY = "IDREntity"

ALL_ROLES = (
    ROLE_FACILITY_ADMINISTRATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_REGISTRATION_CLERK,
    ROLE_EMERGENCY_PHYSICIAN,
    ROLE_HOSPITAL_TRANSFER_COORDINATOR,
    ROLE_PAYER_REPRESENTATIVE,
    ROLE_IDR_ENTITY,
)

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, ROLE_FACILITY_ADMINISTRATOR),
    "second_admin_headers": build_user_headers(
        SECOND_ADMIN_USER_ID, ROLE_FACILITY_ADMINISTRATOR
    ),
    "compliance_officer_headers": build_user_headers(CO_USER_ID, ROLE_COMPLIANCE_OFFICER),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_CO_USER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    "clerk_headers": build_user_headers(CLERK_USER_ID, ROLE_REGISTRATION_CLERK),
    "second_clerk_headers": build_user_headers(
        SECOND_CLERK_USER_ID, ROLE_REGISTRATION_CLERK
    ),
    "physician_headers": build_user_headers(PHYSICIAN_USER_ID, ROLE_EMERGENCY_PHYSICIAN),
    "coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, ROLE_HOSPITAL_TRANSFER_COORDINATOR
    ),
    "payer_headers": build_user_headers(PAYER_USER_ID, ROLE_PAYER_REPRESENTATIVE),
    "idre_headers": build_user_headers(IDRE_USER_ID, ROLE_IDR_ENTITY),
}


def make_admin_headers(user_id: str) -> dict:
    """FacilityAdministrator headers for a named operator.

    The operator identifier matters here because publication records it as the
    template's ``published_by_user_id``, which the signage control later reads.
    """
    return build_user_headers(user_id, ROLE_FACILITY_ADMINISTRATOR)


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_clerk_headers(user_id: str) -> dict:
    """RegistrationClerk headers for a named operator.

    Registration records it as ``registered_by_user_id``, which the emergent
    waiver control later reads.
    """
    return build_user_headers(user_id, ROLE_REGISTRATION_CLERK)


def make_physician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_EMERGENCY_PHYSICIAN)


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_HOSPITAL_TRANSFER_COORDINATOR)


def make_payer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_PAYER_REPRESENTATIVE)


def make_idre_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_IDR_ENTITY)


def make_role_headers(role: str, user_id: str = "operator-x") -> dict:
    """Headers for an arbitrary role name, including undeclared ones."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers carrying ``X-User-ID`` but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = ROLE_FACILITY_ADMINISTRATOR) -> dict:
    """Headers carrying ``X-User-Role`` but no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
