"""Caller identities and the two headers every request carries (PRD §2.1).

``Developer`` and ``Investor`` are entity-backed: the acting ``X-User-ID`` is the
``id`` of the stored row, and ownership checks compare a resource's foreign key
against it. Headers for those two roles therefore only make sense once the
backing row exists, which is why they are built by a function rather than held as
a constant. The four operator identities are opaque and never matched against any
entity ``id``, so a fixed string is always acceptable for them.

Three distinct allocation-officer identities exist because the credit certificate
may not be issued by the officer who awarded the cap or by the officer who
accepted the cost certification.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    MISSING_UUID_A,
    MISSING_UUID_B,
    ROLE_BOND_TRUSTEE,
    ROLE_DEVELOPER,
    ROLE_HFA_ALLOCATION_OFFICER,
    ROLE_HFA_COMPLIANCE_OFFICER,
    ROLE_INVESTOR,
    ROLE_SYSTEM_OPERATOR,
)

# Opaque operator identifiers (PRD §2.1).
ALLOCATION_OFFICER_USER_ID = "hfa-alloc-1"
SECOND_ALLOCATION_OFFICER_USER_ID = "hfa-alloc-2"
THIRD_ALLOCATION_OFFICER_USER_ID = "hfa-alloc-3"
COMPLIANCE_OFFICER_USER_ID = "hfa-comp-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "hfa-comp-2"
TRUSTEE_USER_ID = "trustee-1"
SECOND_TRUSTEE_USER_ID = "trustee-2"
SYSTEM_OPERATOR_USER_ID = "sysop-1"

# Placeholders for the entity-backed roles, used only where the request is
# refused before the identifier is ever compared with stored data — an
# unauthorized role, or a path identifier that resolves to nothing.
PLACEHOLDER_DEVELOPER_USER_ID = MISSING_UUID_A
PLACEHOLDER_INVESTOR_USER_ID = MISSING_UUID_B


def make_developer_headers(developer_id):
    """Headers for a Developer acting as the sponsor row with this id."""
    return build_user_headers(str(developer_id), ROLE_DEVELOPER)


def make_investor_headers(investor_id):
    """Headers for an Investor acting as the investor row with this id."""
    return build_user_headers(str(investor_id), ROLE_INVESTOR)


def make_allocation_officer_headers(user_id=ALLOCATION_OFFICER_USER_ID):
    """Headers for an HfaAllocationOfficer, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_HFA_ALLOCATION_OFFICER)


def make_compliance_officer_headers(user_id=COMPLIANCE_OFFICER_USER_ID):
    """Headers for an HfaComplianceOfficer, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_HFA_COMPLIANCE_OFFICER)


def make_trustee_headers(user_id=TRUSTEE_USER_ID):
    """Headers for a BondTrustee, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_BOND_TRUSTEE)


def make_system_operator_headers(user_id=SYSTEM_OPERATOR_USER_ID):
    """Headers for the SystemOperator that owns the logical clock."""
    return build_user_headers(str(user_id), ROLE_SYSTEM_OPERATOR)


def make_headers(role, user_id):
    """Headers for an arbitrary role and identifier pair."""
    return build_user_headers(str(user_id), role)


def make_headers_without_role(user_id):
    """Headers carrying an identifier but no X-User-Role at all (PRD §2.1)."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def make_headers_without_user_id(role):
    """Headers declaring a role but omitting X-User-ID entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_blank_role(user_id):
    """Headers whose X-User-Role is the empty string (PRD §2.1)."""
    return {
        "X-User-ID": str(user_id),
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def make_headers_with_blank_user_id(role):
    """Headers whose X-User-ID is the empty string (PRD §2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


ALLOCATION_OFFICER = make_allocation_officer_headers()
SECOND_ALLOCATION_OFFICER = make_allocation_officer_headers(
    SECOND_ALLOCATION_OFFICER_USER_ID
)
THIRD_ALLOCATION_OFFICER = make_allocation_officer_headers(
    THIRD_ALLOCATION_OFFICER_USER_ID
)
COMPLIANCE_OFFICER = make_compliance_officer_headers()
SECOND_COMPLIANCE_OFFICER = make_compliance_officer_headers(
    SECOND_COMPLIANCE_OFFICER_USER_ID
)
TRUSTEE = make_trustee_headers()
SECOND_TRUSTEE = make_trustee_headers(SECOND_TRUSTEE_USER_ID)
SYSTEM_OPERATOR = make_system_operator_headers()

TEST_USERS = {
    ROLE_HFA_ALLOCATION_OFFICER: ALLOCATION_OFFICER,
    ROLE_HFA_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    ROLE_BOND_TRUSTEE: TRUSTEE,
    ROLE_SYSTEM_OPERATOR: SYSTEM_OPERATOR,
    # Entity-backed placeholders; only for refusals that land before identity
    # is ever compared against stored data.
    ROLE_DEVELOPER: make_developer_headers(PLACEHOLDER_DEVELOPER_USER_ID),
    ROLE_INVESTOR: make_investor_headers(PLACEHOLDER_INVESTOR_USER_ID),
}
