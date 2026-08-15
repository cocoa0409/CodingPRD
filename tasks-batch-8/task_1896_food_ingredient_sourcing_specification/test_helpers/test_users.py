"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque: X-User-ID is an operator identifier recorded onto
segregation-of-duties anchor fields, never compared to an entity primary key.
Shared constants are the canonical form; the make_*_headers builders exist for
tests that must control the operator id (segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_1,
    AUTHOR_1,
    PM_1,
    QM_1,
    RA_1,
    SQE_1,
)
from .types import UserRole

TEST_USERS = {
    "spec_author_headers": build_user_headers(AUTHOR_1, UserRole.SPEC_AUTHOR.value),
    "quality_manager_headers": build_user_headers(QM_1, UserRole.QUALITY_MANAGER.value),
    "procurement_manager_headers": build_user_headers(PM_1, UserRole.PROCUREMENT_MANAGER.value),
    "sqe_headers": build_user_headers(SQE_1, UserRole.SUPPLIER_QUALITY_ENGINEER.value),
    "regulatory_affairs_headers": build_user_headers(RA_1, UserRole.REGULATORY_AFFAIRS.value),
    "platform_admin_headers": build_user_headers(ADMIN_1, UserRole.PLATFORM_ADMIN.value),
}


def make_spec_author_headers(user_id: str) -> dict:
    """SpecAuthor headers with a specific operator id (author segregation anchor)."""
    return build_user_headers(user_id, UserRole.SPEC_AUTHOR.value)


def make_quality_manager_headers(user_id: str) -> dict:
    """QualityManager headers with a specific operator id (approver/closer anchor)."""
    return build_user_headers(user_id, UserRole.QUALITY_MANAGER.value)


def make_procurement_manager_headers(user_id: str) -> dict:
    """ProcurementManager headers with a specific operator id (requester anchor)."""
    return build_user_headers(user_id, UserRole.PROCUREMENT_MANAGER.value)


def make_sqe_headers(user_id: str) -> dict:
    """SupplierQualityEngineer headers with a specific operator id (registrar anchor)."""
    return build_user_headers(user_id, UserRole.SUPPLIER_QUALITY_ENGINEER.value)


def make_regulatory_affairs_headers(user_id: str) -> dict:
    """RegulatoryAffairs headers with a specific operator id."""
    return build_user_headers(user_id, UserRole.REGULATORY_AFFAIRS.value)


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers with a specific operator id."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)
