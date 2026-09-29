"""Acting principals and their request headers.

Every request carries ``X-User-ID`` identifying the acting principal and
``X-User-Role`` declaring the capacity in which it acts.

``ParentGuardian`` is the one role whose ``X-User-ID`` is not opaque: it is the
``id`` of the acting enrollment, so parent-guardian headers must always be built
from a real enrollment id with :func:`make_parent_guardian_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities. Distinct ids inside one role let a test satisfy
# the separation-of-duties rules that compare two acting user ids.
TEST_USERS = {
    "intake_coordinator": {"user_id": "ic-001", "role": UserRole.INTAKE_COORDINATOR.value},
    "intake_coordinator_2": {"user_id": "ic-002", "role": UserRole.INTAKE_COORDINATOR.value},
    "collection_site": {"user_id": "cs-001", "role": UserRole.COLLECTION_SITE.value},
    "collection_site_2": {"user_id": "cs-002", "role": UserRole.COLLECTION_SITE.value},
    "technologist": {"user_id": "tech-001", "role": UserRole.PROCESSING_TECHNOLOGIST.value},
    "technologist_2": {"user_id": "tech-002", "role": UserRole.PROCESSING_TECHNOLOGIST.value},
    "processing_tech_alt": {"user_id": "pt-001", "role": UserRole.PROCESSING_TECHNOLOGIST.value},
    "processing_tech_alt_2": {"user_id": "pt-002", "role": UserRole.PROCESSING_TECHNOLOGIST.value},
    "dual_hat_technologist": {"user_id": "dual-001", "role": UserRole.PROCESSING_TECHNOLOGIST.value},
    "medical_director": {"user_id": "md-001", "role": UserRole.MEDICAL_DIRECTOR.value},
    "medical_director_2": {"user_id": "md-002", "role": UserRole.MEDICAL_DIRECTOR.value},
    "dual_hat_director": {"user_id": "dual-001", "role": UserRole.MEDICAL_DIRECTOR.value},
    "registry_operator": {"user_id": "ro-001", "role": UserRole.REGISTRY_OPERATOR.value},
    "transplant_center": {"user_id": "tc-001", "role": UserRole.TRANSPLANT_CENTER.value},
    "transplant_center_2": {"user_id": "tc-002", "role": UserRole.TRANSPLANT_CENTER.value},
    "transplant_center_3": {"user_id": "tc-003", "role": UserRole.TRANSPLANT_CENTER.value},
    "transplant_center_4": {"user_id": "tc-004", "role": UserRole.TRANSPLANT_CENTER.value},
    "billing_admin": {"user_id": "ba-001", "role": UserRole.BILLING_ADMINISTRATOR.value},
    "facilities_engineer": {"user_id": "fe-001", "role": UserRole.FACILITIES_ENGINEER.value},
    "facilities_engineer_2": {"user_id": "fe-002", "role": UserRole.FACILITIES_ENGINEER.value},
    "platform_admin": {"user_id": "admin-001", "role": UserRole.PLATFORM_ADMIN.value},
}

# An identifier paired with a role name the PRD does not declare.
UNDECLARED_ROLE_NAME = "AuditorGeneral"
UNDECLARED_ROLE_USER_ID = "xx-001"


def _headers(key: str) -> dict:
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def make_intake_coordinator_headers(user_id: str = "ic-001") -> dict:
    return build_user_headers(user_id, UserRole.INTAKE_COORDINATOR.value)


def make_parent_guardian_headers(enrollment_id: str) -> dict:
    """Headers for a family acting on its own enrollment.

    ``X-User-ID`` is the ``id`` of the acting enrollment; ownership checks
    compare a resource's enrollment foreign key against it.
    """
    return build_user_headers(enrollment_id, UserRole.PARENT_GUARDIAN.value)


def make_collection_site_headers(user_id: str = "cs-001") -> dict:
    return build_user_headers(user_id, UserRole.COLLECTION_SITE.value)


def make_technologist_headers(user_id: str = "tech-001") -> dict:
    return build_user_headers(user_id, UserRole.PROCESSING_TECHNOLOGIST.value)


def make_medical_director_headers(user_id: str = "md-001") -> dict:
    return build_user_headers(user_id, UserRole.MEDICAL_DIRECTOR.value)


def make_registry_operator_headers(user_id: str = "ro-001") -> dict:
    return build_user_headers(user_id, UserRole.REGISTRY_OPERATOR.value)


def make_transplant_center_headers(user_id: str = "tc-001") -> dict:
    return build_user_headers(user_id, UserRole.TRANSPLANT_CENTER.value)


def make_billing_admin_headers(user_id: str = "ba-001") -> dict:
    return build_user_headers(user_id, UserRole.BILLING_ADMINISTRATOR.value)


def make_facilities_engineer_headers(user_id: str = "fe-001") -> dict:
    return build_user_headers(user_id, UserRole.FACILITIES_ENGINEER.value)


def make_platform_admin_headers(user_id: str = "admin-001") -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role name, including names the PRD never declares."""
    return build_user_headers(user_id, role)


# Convenience singletons for the opaque roles.
INTAKE_COORDINATOR_HEADERS = make_intake_coordinator_headers()
COLLECTION_SITE_HEADERS = make_collection_site_headers()
TECHNOLOGIST_HEADERS = make_technologist_headers()
MEDICAL_DIRECTOR_HEADERS = make_medical_director_headers()
REGISTRY_OPERATOR_HEADERS = make_registry_operator_headers()
TRANSPLANT_CENTER_HEADERS = make_transplant_center_headers()
BILLING_ADMIN_HEADERS = make_billing_admin_headers()
FACILITIES_ENGINEER_HEADERS = make_facilities_engineer_headers()
PLATFORM_ADMIN_HEADERS = make_platform_admin_headers()
