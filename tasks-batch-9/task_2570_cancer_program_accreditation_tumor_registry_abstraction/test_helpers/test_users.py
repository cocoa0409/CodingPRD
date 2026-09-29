"""Role headers.

Every request carries ``X-User-ID`` and ``X-User-Role``. For the two roles that
are backed by an ``Abstractor`` record (``RegistryAbstractor`` and
``QaReviewer``) the ``X-User-ID`` value must be the identifier of that
abstractor, so those headers can only be built once the record exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


def _role_value(role):
    """Accept either a plain string or a ``UserRole`` member."""
    return getattr(role, "value", role)

# --- stable identities for the roles that are not entity backed --------------
PLATFORM_ADMIN_USER_ID = "11111111-1111-4111-8111-111111111111"
REGISTRY_MANAGER_USER_ID = "22222222-2222-4222-8222-222222222222"
REGISTRY_MANAGER_2_USER_ID = "22222222-2222-4222-8222-2222222222b2"
ACCREDITATION_COORDINATOR_USER_ID = "33333333-3333-4333-8333-333333333333"
ACCREDITATION_COORDINATOR_2_USER_ID = "33333333-3333-4333-8333-3333333333b3"
STATE_REGISTRY_LIAISON_USER_ID = "44444444-4444-4444-8444-444444444444"
COC_SURVEYOR_USER_ID = "55555555-5555-4555-8555-555555555555"
COC_SURVEYOR_2_USER_ID = "55555555-5555-4555-8555-5555555555b5"
UNKNOWN_ROLE_USER_ID = "66666666-6666-4666-8666-666666666666"

PLATFORM_ADMIN = build_user_headers(
    PLATFORM_ADMIN_USER_ID, _role_value(UserRole.PLATFORM_ADMIN)
)
REGISTRY_MANAGER = build_user_headers(
    REGISTRY_MANAGER_USER_ID, _role_value(UserRole.REGISTRY_MANAGER)
)
REGISTRY_MANAGER_2 = build_user_headers(
    REGISTRY_MANAGER_2_USER_ID, _role_value(UserRole.REGISTRY_MANAGER)
)
ACCREDITATION_COORDINATOR = build_user_headers(
    ACCREDITATION_COORDINATOR_USER_ID, _role_value(UserRole.ACCREDITATION_COORDINATOR)
)
ACCREDITATION_COORDINATOR_2 = build_user_headers(
    ACCREDITATION_COORDINATOR_2_USER_ID, _role_value(UserRole.ACCREDITATION_COORDINATOR)
)
STATE_REGISTRY_LIAISON = build_user_headers(
    STATE_REGISTRY_LIAISON_USER_ID, _role_value(UserRole.STATE_REGISTRY_LIAISON)
)
COC_SURVEYOR = build_user_headers(
    COC_SURVEYOR_USER_ID, _role_value(UserRole.COC_SURVEYOR)
)
COC_SURVEYOR_2 = build_user_headers(
    COC_SURVEYOR_2_USER_ID, _role_value(UserRole.COC_SURVEYOR)
)


# --- per-instance builders ---------------------------------------------------
def make_platform_admin_headers(user_id=PLATFORM_ADMIN_USER_ID):
    return build_user_headers(user_id, _role_value(UserRole.PLATFORM_ADMIN))


def make_registry_manager_headers(user_id=REGISTRY_MANAGER_USER_ID):
    return build_user_headers(user_id, _role_value(UserRole.REGISTRY_MANAGER))


def make_registry_abstractor_headers(abstractor_id):
    """``X-User-ID`` must be the identifier of the acting abstractor."""
    return build_user_headers(abstractor_id, _role_value(UserRole.REGISTRY_ABSTRACTOR))


def make_qa_reviewer_headers(abstractor_id):
    """``X-User-ID`` must be the identifier of the reviewing abstractor."""
    return build_user_headers(abstractor_id, _role_value(UserRole.QA_REVIEWER))


def make_accreditation_coordinator_headers(user_id=ACCREDITATION_COORDINATOR_USER_ID):
    return build_user_headers(user_id, _role_value(UserRole.ACCREDITATION_COORDINATOR))


def make_state_registry_liaison_headers(user_id=STATE_REGISTRY_LIAISON_USER_ID):
    return build_user_headers(user_id, _role_value(UserRole.STATE_REGISTRY_LIAISON))


def make_coc_surveyor_headers(user_id=COC_SURVEYOR_USER_ID):
    return build_user_headers(user_id, _role_value(UserRole.COC_SURVEYOR))


def make_headers(user_id, role):
    """Escape hatch for negative authentication and authorization cases."""
    return build_user_headers(user_id, _role_value(role))


ALL_ROLES = [
    UserRole.PLATFORM_ADMIN,
    UserRole.REGISTRY_MANAGER,
    UserRole.REGISTRY_ABSTRACTOR,
    UserRole.QA_REVIEWER,
    UserRole.ACCREDITATION_COORDINATOR,
    UserRole.STATE_REGISTRY_LIAISON,
    UserRole.COC_SURVEYOR,
]

ENTITY_BACKED_ROLES = [UserRole.REGISTRY_ABSTRACTOR, UserRole.QA_REVIEWER]
