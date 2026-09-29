"""Header builders for the six roles the PRD declares (PRD 2.1).

`GovernanceStaff` and `CorporateSecretary` carry opaque operator identifiers
that the server never compares to any entity id, so a fixed identifier is safe
for them.  The remaining four roles are entity-backed: `X-User-ID` must be the
`id` of the acting `Director` (or `SearchFirm`), so those headers are always
built from a real entity id via the `make_*` helpers below.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities (never compared to an entity id).
GOVERNANCE_STAFF_USER_ID = "staff-operator-1"
CORPORATE_SECRETARY_USER_ID = "secretary-operator-1"

TEST_USERS = {
    "governance_staff": build_user_headers(
        GOVERNANCE_STAFF_USER_ID, UserRole.GOVERNANCE_STAFF.value
    ),
    "corporate_secretary": build_user_headers(
        CORPORATE_SECRETARY_USER_ID, UserRole.CORPORATE_SECRETARY.value
    ),
}

STAFF = TEST_USERS["governance_staff"]
SECRETARY = TEST_USERS["corporate_secretary"]


def make_committee_chair_headers(director_id):
    """Headers for a `CommitteeChair` acting as the given `Director`."""
    return build_user_headers(director_id, UserRole.COMMITTEE_CHAIR.value)


def make_committee_member_headers(director_id):
    """Headers for a `CommitteeMember` acting as the given `Director`."""
    return build_user_headers(director_id, UserRole.COMMITTEE_MEMBER.value)


def make_seated_director_headers(director_id):
    """Headers for a `SeatedDirector` acting for themselves."""
    return build_user_headers(director_id, UserRole.SEATED_DIRECTOR.value)


def make_search_firm_partner_headers(search_firm_id):
    """Headers for a `SearchFirmPartner` acting for the given `SearchFirm`."""
    return build_user_headers(search_firm_id, UserRole.SEARCH_FIRM_PARTNER.value)


def make_headers(role, subject_id):
    """Headers for any role, given the identifier that role's `X-User-ID` takes."""
    value = role.value if isinstance(role, UserRole) else role
    return build_user_headers(subject_id, value)


def headers_missing_role(user_id=GOVERNANCE_STAFF_USER_ID):
    """A request that omits `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role=UserRole.GOVERNANCE_STAFF):
    """A request that omits `X-User-ID` entirely."""
    value = role.value if isinstance(role, UserRole) else role
    return {"X-User-Role": value, "Content-Type": "application/json"}


def headers_empty_role(user_id=GOVERNANCE_STAFF_USER_ID):
    """A request whose `X-User-Role` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_empty_user_id(role=UserRole.GOVERNANCE_STAFF):
    """A request whose `X-User-ID` is present but empty."""
    value = role.value if isinstance(role, UserRole) else role
    return {"X-User-ID": "", "X-User-Role": value, "Content-Type": "application/json"}


def headers_unrecognised_role(user_id=GOVERNANCE_STAFF_USER_ID):
    """A request declaring a role name that is not one of the six."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "BoardObserver",
        "Content-Type": "application/json",
    }
