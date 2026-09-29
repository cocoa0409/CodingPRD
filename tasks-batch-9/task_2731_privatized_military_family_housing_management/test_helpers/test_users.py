"""Pre-built request headers for every role the PRD declares.

For the five operator roles ``X-User-ID`` is an opaque operator identifier not
tied to any persisted entity, so a shared constant is the canonical form. For
``ServiceMember`` the ``X-User-ID`` is the ``id`` of the acting ServiceMember
record, so ownership-gated calls MUST use ``make_service_member_headers()``
with the real sponsor id.
"""

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_USER_ID = "admin-user-1"
PROPERTY_MANAGER_USER_ID = "pm-user-1"
PROPERTY_MANAGER_USER_ID_2 = "pm-user-2"
MAINTENANCE_TECH_USER_ID = "tech-user-1"
MAINTENANCE_TECH_USER_ID_2 = "tech-user-2"
MAINTENANCE_TECH_USER_ID_3 = "tech-user-3"
ENVIRONMENTAL_SPECIALIST_USER_ID = "es-user-1"
ENVIRONMENTAL_SPECIALIST_USER_ID_2 = "es-user-2"
INSTALLATION_HOUSING_OFFICE_USER_ID = "iho-user-1"
INSTALLATION_HOUSING_OFFICE_USER_ID_2 = "iho-user-2"

# A placeholder sponsor identifier. Safe only for tests that never reach an
# ownership comparison (bad payloads, missing resources, role rejections).
SERVICE_MEMBER_PLACEHOLDER_USER_ID = "sm-user-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
    "property_manager_headers": build_user_headers(
        PROPERTY_MANAGER_USER_ID, "PropertyManager"
    ),
    "property_manager_2_headers": build_user_headers(
        PROPERTY_MANAGER_USER_ID_2, "PropertyManager"
    ),
    "maintenance_tech_headers": build_user_headers(
        MAINTENANCE_TECH_USER_ID, "MaintenanceTech"
    ),
    "environmental_specialist_headers": build_user_headers(
        ENVIRONMENTAL_SPECIALIST_USER_ID, "EnvironmentalSpecialist"
    ),
    "environmental_specialist_2_headers": build_user_headers(
        ENVIRONMENTAL_SPECIALIST_USER_ID_2, "EnvironmentalSpecialist"
    ),
    "installation_housing_office_headers": build_user_headers(
        INSTALLATION_HOUSING_OFFICE_USER_ID, "InstallationHousingOffice"
    ),
    "installation_housing_office_2_headers": build_user_headers(
        INSTALLATION_HOUSING_OFFICE_USER_ID_2, "InstallationHousingOffice"
    ),
    # Fallback only — never use where an ownership check runs.
    "service_member_headers": build_user_headers(
        SERVICE_MEMBER_PLACEHOLDER_USER_ID, "ServiceMember"
    ),
}


def make_service_member_headers(service_member_id: str) -> dict:
    """Headers for the sponsor role. Pass the real ServiceMember ``id``."""
    return build_user_headers(service_member_id, "ServiceMember")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_property_manager_headers(user_id: str = PROPERTY_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_maintenance_tech_headers(user_id: str = MAINTENANCE_TECH_USER_ID) -> dict:
    return build_user_headers(user_id, "MaintenanceTech")


def make_environmental_specialist_headers(
    user_id: str = ENVIRONMENTAL_SPECIALIST_USER_ID,
) -> dict:
    return build_user_headers(user_id, "EnvironmentalSpecialist")


def make_installation_housing_office_headers(
    user_id: str = INSTALLATION_HOUSING_OFFICE_USER_ID,
) -> dict:
    return build_user_headers(user_id, "InstallationHousingOffice")


ALL_ROLE_NAMES = [
    "PlatformAdmin",
    "PropertyManager",
    "ServiceMember",
    "MaintenanceTech",
    "EnvironmentalSpecialist",
    "InstallationHousingOffice",
]
