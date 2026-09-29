"""Test users and header builders for the seven PRD roles.

Five roles are opaque: the PRD's authorization check depends only on the role
string, so a pinned user id per role is sufficient. Two roles are entity-backed
and the PRD requires ``X-User-ID`` to equal the owning row id, so those roles
have no shared constant — headers must be built per row.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# --------------------------------------------------------------------------
# Role names
# --------------------------------------------------------------------------
ROLE_MASTER_SERVICER = "MasterServicer"
ROLE_ASSET_MANAGER = "SpecialServicerAssetManager"
ROLE_COMMITTEE_OFFICER = "SpecialServicingCommitteeOfficer"
ROLE_CONTROLLING_CLASS = "ControllingClassRepresentative"
ROLE_BORROWER = "Borrower"
ROLE_TRUSTEE = "Trustee"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_MASTER_SERVICER,
    ROLE_ASSET_MANAGER,
    ROLE_COMMITTEE_OFFICER,
    ROLE_CONTROLLING_CLASS,
    ROLE_BORROWER,
    ROLE_TRUSTEE,
    ROLE_PLATFORM_ADMIN,
]

# --------------------------------------------------------------------------
# Pinned user ids for the opaque roles
# --------------------------------------------------------------------------
MASTER_SERVICER_ID = "ms-001"
ASSET_MANAGER_ID = "amgr-001"
# A second, distinct asset manager so the segregation-of-duties rule can be
# satisfied: the human who authors a row may never bless it.
ASSET_MANAGER_2_ID = "amgr-002"
COMMITTEE_OFFICER_ID = "cmte-001"
TRUSTEE_ID = "trustee-001"
PLATFORM_ADMIN_ID = "admin-001"

# --------------------------------------------------------------------------
# Shared headers for the opaque roles
# --------------------------------------------------------------------------
MASTER_SERVICER = build_user_headers(MASTER_SERVICER_ID, ROLE_MASTER_SERVICER)
ASSET_MANAGER = build_user_headers(ASSET_MANAGER_ID, ROLE_ASSET_MANAGER)
ASSET_MANAGER_2 = build_user_headers(ASSET_MANAGER_2_ID, ROLE_ASSET_MANAGER)
COMMITTEE_OFFICER = build_user_headers(COMMITTEE_OFFICER_ID, ROLE_COMMITTEE_OFFICER)
TRUSTEE = build_user_headers(TRUSTEE_ID, ROLE_TRUSTEE)
PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)

TEST_USERS = {
    ROLE_MASTER_SERVICER: MASTER_SERVICER,
    ROLE_ASSET_MANAGER: ASSET_MANAGER,
    ROLE_COMMITTEE_OFFICER: COMMITTEE_OFFICER,
    ROLE_TRUSTEE: TRUSTEE,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
}

OPAQUE_ROLE_IDS = {
    ROLE_MASTER_SERVICER: MASTER_SERVICER_ID,
    ROLE_ASSET_MANAGER: ASSET_MANAGER_ID,
    ROLE_COMMITTEE_OFFICER: COMMITTEE_OFFICER_ID,
    ROLE_TRUSTEE: TRUSTEE_ID,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN_ID,
}


# --------------------------------------------------------------------------
# Per-instance builders for the entity-backed roles
# --------------------------------------------------------------------------
def make_borrower_headers(loan_id: str) -> Headers:
    """Headers for the Borrower of one specific loan.

    The PRD backs the Borrower role with the Loan row, so ``X-User-ID`` must
    carry the acting ``Loan.id``.
    """
    return build_user_headers(loan_id, ROLE_BORROWER)


def make_controlling_class_representative_headers(trust_id: str) -> Headers:
    """Headers for the ControllingClassRepresentative of one specific trust.

    The PRD backs this role with the Trust row, so ``X-User-ID`` must carry the
    acting ``Trust.id``.
    """
    return build_user_headers(trust_id, ROLE_CONTROLLING_CLASS)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary (role, user id) pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, loan_id: str = "", trust_id: str = "") -> Headers:
    """Resolve headers for any role, threading identity for the entity-backed ones."""
    if role == ROLE_BORROWER:
        return make_borrower_headers(loan_id)
    if role == ROLE_CONTROLLING_CLASS:
        return make_controlling_class_representative_headers(trust_id)
    return TEST_USERS[role]
