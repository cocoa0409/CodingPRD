"""Pre-built role headers for the seven roles of PRD §2.1.

Opaque roles (PlatformAdmin, TalentManager, BrandManager, ComplianceOfficer,
FinanceAdmin) carry operator identifiers not tied to any persisted entity;
the shared constants below are their canonical form. The entity-backed roles
(Creator, Brand) must instead be built per instance with make_creator_headers
/ make_brand_headers so that X-User-ID equals the actual entity id whenever
the call is ownership-gated (PRD §2.1, §2.8 rule 3).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    BM_USER_ID,
    BM_USER_ID_2,
    CO_USER_ID,
    FIN_USER_ID,
    FIN_USER_ID_2,
    TM_USER_ID,
)
from .types import UserRole

TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
    "talent_manager_headers": build_user_headers(
        TM_USER_ID, UserRole.TALENT_MANAGER.value
    ),
    "brand_manager_headers": build_user_headers(
        BM_USER_ID, UserRole.BRAND_MANAGER.value
    ),
    "brand_manager_2_headers": build_user_headers(
        BM_USER_ID_2, UserRole.BRAND_MANAGER.value
    ),
    "compliance_officer_headers": build_user_headers(
        CO_USER_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "finance_admin_headers": build_user_headers(
        FIN_USER_ID, UserRole.FINANCE_ADMIN.value
    ),
    "finance_admin_2_headers": build_user_headers(
        FIN_USER_ID_2, UserRole.FINANCE_ADMIN.value
    ),
    # Entity-backed fallbacks: only safe for non-ownership-gated calls.
    "creator_headers": build_user_headers("creator-fallback", UserRole.CREATOR.value),
    "brand_headers": build_user_headers("brand-fallback", UserRole.BRAND.value),
}


def make_creator_headers(user_id: str) -> dict:
    """Creator role headers bound to a concrete Creator.id (entity-backed role).

    Pass the acting creator's own id for ownership-gated calls
    (creator-respond, submit, publish, requeue, reshoot respond, disputes).
    """
    return build_user_headers(user_id, UserRole.CREATOR.value)


def make_brand_headers(user_id: str) -> dict:
    """Brand role headers bound to a concrete Brand.id (entity-backed role).

    Pass the acting brand's own id for ownership-gated calls
    (brand-respond, disputes).
    """
    return build_user_headers(user_id, UserRole.BRAND.value)


def make_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a chosen operator id.

    Used to exercise the disclosure segregation-of-duties rule by reusing the
    approving BrandManager's operator id as the reviewing officer's id.
    """
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_finance_headers(user_id: str) -> dict:
    """FinanceAdmin headers with a chosen operator id (issuer vs releaser)."""
    return build_user_headers(user_id, UserRole.FINANCE_ADMIN.value)


def make_headers_without_role(user_id: str) -> dict:
    """Headers carrying X-User-ID but no X-User-Role (incomplete auth context)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
