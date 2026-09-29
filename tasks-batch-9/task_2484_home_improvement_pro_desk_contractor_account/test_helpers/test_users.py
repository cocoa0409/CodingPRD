"""Pre-built role headers for every role the PRD declares.

Two flavours are exported per role:

* a shared-constant entry in ``TEST_USERS`` — safe for roles whose identity is
  opaque, and for tests whose success does not depend on the caller owning the
  subject resource;
* a per-instance builder ``make_<role>_headers(user_id)`` — mandatory for
  ``ContractorAdmin``, whose identity is the pro account it acts for. Any
  ownership-gated ContractorAdmin call must pass the real ``ProAccount.id``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Fixed opaque identities used across the suite.
PLATFORM_ADMIN_USER_ID = "admin-1"
PRO_DESK_ASSOCIATE_USER_ID = "assoc-1"
SECOND_PRO_DESK_ASSOCIATE_USER_ID = "assoc-2"
CREDIT_MANAGER_USER_ID = "cm-1"
SECOND_CREDIT_MANAGER_USER_ID = "cm-2"
STORE_OPERATIONS_USER_ID = "ops-1"
TAX_COMPLIANCE_OFFICER_USER_ID = "tax-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
    "pro_desk_associate_headers": build_user_headers(
        PRO_DESK_ASSOCIATE_USER_ID, UserRole.PRO_DESK_ASSOCIATE.value
    ),
    "second_pro_desk_associate_headers": build_user_headers(
        SECOND_PRO_DESK_ASSOCIATE_USER_ID, UserRole.PRO_DESK_ASSOCIATE.value
    ),
    "credit_manager_headers": build_user_headers(
        CREDIT_MANAGER_USER_ID, UserRole.CREDIT_MANAGER.value
    ),
    "second_credit_manager_headers": build_user_headers(
        SECOND_CREDIT_MANAGER_USER_ID, UserRole.CREDIT_MANAGER.value
    ),
    "store_operations_headers": build_user_headers(
        STORE_OPERATIONS_USER_ID, UserRole.STORE_OPERATIONS.value
    ),
    "tax_compliance_officer_headers": build_user_headers(
        TAX_COMPLIANCE_OFFICER_USER_ID, UserRole.TAX_COMPLIANCE_OFFICER.value
    ),
    # ContractorAdmin is backed by a pro account: this shared constant is only a
    # fallback for probes that never reach an ownership check.
    "contractor_admin_headers": build_user_headers(
        "test-contractor-admin-1", UserRole.CONTRACTOR_ADMIN.value
    ),
}


def make_contractor_admin_headers(user_id: str) -> dict:
    """Headers for the contractor's own buyer.

    ``user_id`` must be the ``ProAccount.id`` the caller acts for, because the
    API resolves a ContractorAdmin's identity to that account.
    """
    return build_user_headers(user_id, UserRole.CONTRACTOR_ADMIN.value)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_pro_desk_associate_headers(
    user_id: str = PRO_DESK_ASSOCIATE_USER_ID,
) -> dict:
    return build_user_headers(user_id, UserRole.PRO_DESK_ASSOCIATE.value)


def make_credit_manager_headers(user_id: str = CREDIT_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.CREDIT_MANAGER.value)


def make_store_operations_headers(user_id: str = STORE_OPERATIONS_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.STORE_OPERATIONS.value)


def make_tax_compliance_officer_headers(
    user_id: str = TAX_COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    return build_user_headers(user_id, UserRole.TAX_COMPLIANCE_OFFICER.value)


# Convenience aliases used throughout the suite.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
PRO_DESK_ASSOCIATE = TEST_USERS["pro_desk_associate_headers"]
SECOND_PRO_DESK_ASSOCIATE = TEST_USERS["second_pro_desk_associate_headers"]
CREDIT_MANAGER = TEST_USERS["credit_manager_headers"]
SECOND_CREDIT_MANAGER = TEST_USERS["second_credit_manager_headers"]
STORE_OPERATIONS = TEST_USERS["store_operations_headers"]
TAX_COMPLIANCE_OFFICER = TEST_USERS["tax_compliance_officer_headers"]
