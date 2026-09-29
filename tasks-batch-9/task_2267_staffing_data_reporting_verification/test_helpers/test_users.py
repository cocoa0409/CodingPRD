"""Pre-built role headers for every role in the PRD.

`PlatformAdmin`, `StateAuditor`, `CmsPublisher`, and `AppealsReviewer` carry an
opaque operator identifier, so the shared constants below are the canonical
form for them.

`StaffingCoordinator` and `FacilityAdministrator` carry the acting `Worker`'s
`id`; `VendorRepresentative` carries the acting `StaffingVendor`'s `id`. For
those three roles every ownership-gated call MUST use the matching
`make_*_headers(...)` builder with the real entity id — the shared constants are
only usable where no identity resolution is expected to succeed.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ACCEPTING_AUDITOR_USER_ID,
    CASE_AUDITOR_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    PUBLISHER_USER_ID,
    READING_AUDITOR_USER_ID,
    REVIEWER_USER_ID,
    VERIFYING_AUDITOR_USER_ID,
)
from .types import UserRole

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
    "state_auditor_headers": build_user_headers(
        CASE_AUDITOR_USER_ID, UserRole.STATE_AUDITOR.value
    ),
    "verifying_auditor_headers": build_user_headers(
        VERIFYING_AUDITOR_USER_ID, UserRole.STATE_AUDITOR.value
    ),
    "accepting_auditor_headers": build_user_headers(
        ACCEPTING_AUDITOR_USER_ID, UserRole.STATE_AUDITOR.value
    ),
    "reading_auditor_headers": build_user_headers(
        READING_AUDITOR_USER_ID, UserRole.STATE_AUDITOR.value
    ),
    "case_auditor_headers": build_user_headers(
        CASE_AUDITOR_USER_ID, UserRole.STATE_AUDITOR.value
    ),
    "cms_publisher_headers": build_user_headers(
        PUBLISHER_USER_ID, UserRole.CMS_PUBLISHER.value
    ),
    "appeals_reviewer_headers": build_user_headers(
        REVIEWER_USER_ID, UserRole.APPEALS_REVIEWER.value
    ),
    # Entity-backed roles — fallbacks for tests that deliberately probe an
    # identity that resolves to no row of the backing entity.
    "staffing_coordinator_headers": build_user_headers(
        "not-a-worker-id", UserRole.STAFFING_COORDINATOR.value
    ),
    "facility_administrator_headers": build_user_headers(
        "not-a-worker-id", UserRole.FACILITY_ADMINISTRATOR.value
    ),
    "vendor_representative_headers": build_user_headers(
        "not-a-vendor-id", UserRole.VENDOR_REPRESENTATIVE.value
    ),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    """`PlatformAdmin` acts under an opaque operator identifier."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_staffing_coordinator_headers(worker_id: str) -> dict:
    """For `StaffingCoordinator`. Pass the acting `Worker`'s id."""
    return build_user_headers(worker_id, UserRole.STAFFING_COORDINATOR.value)


def make_facility_administrator_headers(worker_id: str) -> dict:
    """For `FacilityAdministrator`. Pass the acting `Worker`'s id."""
    return build_user_headers(worker_id, UserRole.FACILITY_ADMINISTRATOR.value)


def make_vendor_representative_headers(vendor_id: str) -> dict:
    """For `VendorRepresentative`. Pass the acting `StaffingVendor`'s id."""
    return build_user_headers(vendor_id, UserRole.VENDOR_REPRESENTATIVE.value)


def make_state_auditor_headers(user_id: str) -> dict:
    """For `StateAuditor`. The identity is opaque but segregation of duties
    means the verifying identity and the accepting identity must differ."""
    return build_user_headers(user_id, UserRole.STATE_AUDITOR.value)


def make_cms_publisher_headers(user_id: str = PUBLISHER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.CMS_PUBLISHER.value)


def make_appeals_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.APPEALS_REVIEWER.value)
