"""Caller identities for the six roles of PRD 2.1.

Four of the roles carry an opaque identifier and can therefore be shared across
every test.  Two of them are identity-bearing: PRD 2.5 requires that a
`ProjectSponsor`'s `X-User-ID` equal the sponsoring jurisdiction's own
identifier, and a `JurisdictionDelegate`'s `X-User-ID` equal the identifier of
the jurisdiction whose row is being touched.  Those two must be built per
jurisdiction with the builders below; using a shared constant for them makes
every ownership-gated call fail with a scope violation.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import ALL_ROLES

ALL_ROLE_NAMES = ALL_ROLES

# Opaque identities (PRD 2.1: "an opaque staff identifier").
REGIONAL_ADMINISTRATOR_USER_ID = "admin-01"
HAZARD_ANALYST_USER_ID = "analyst-01"
BCA_REVIEWER_USER_ID = "reviewer-01"
SECOND_BCA_REVIEWER_USER_ID = "reviewer-02"
EQUITY_OFFICER_USER_ID = "equity-01"

UNKNOWN_ROLE_NAME = "ClimateIntern"
UNKNOWN_ROLE_USER_ID = "intern-01"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "RegionalAdministrator": build_user_headers(
        REGIONAL_ADMINISTRATOR_USER_ID, "RegionalAdministrator"
    ),
    "HazardAnalyst": build_user_headers(HAZARD_ANALYST_USER_ID, "HazardAnalyst"),
    "BCAReviewer": build_user_headers(BCA_REVIEWER_USER_ID, "BCAReviewer"),
    "EquityOfficer": build_user_headers(EQUITY_OFFICER_USER_ID, "EquityOfficer"),
}


def make_regional_administrator_headers() -> Dict[str, str]:
    return build_user_headers(REGIONAL_ADMINISTRATOR_USER_ID, "RegionalAdministrator")


def make_hazard_analyst_headers() -> Dict[str, str]:
    return build_user_headers(HAZARD_ANALYST_USER_ID, "HazardAnalyst")


def make_bca_reviewer_headers(user_id: str = BCA_REVIEWER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "BCAReviewer")


def make_equity_officer_headers() -> Dict[str, str]:
    return build_user_headers(EQUITY_OFFICER_USER_ID, "EquityOfficer")


def make_project_sponsor_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Sponsor headers bound to the jurisdiction that owns the project."""
    return build_user_headers(jurisdiction_id, "ProjectSponsor")


def make_jurisdiction_delegate_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Delegate headers bound to the jurisdiction the delegate speaks for."""
    return build_user_headers(jurisdiction_id, "JurisdictionDelegate")


def make_unknown_role_headers() -> Dict[str, str]:
    """A syntactically complete header pair naming a role outside PRD 2.1."""
    return build_user_headers(UNKNOWN_ROLE_USER_ID, UNKNOWN_ROLE_NAME)


def make_role_headers(role: str, user_id: str) -> Dict[str, str]:
    """Header pair for an arbitrary role/identifier combination."""
    return build_user_headers(user_id, role)


def all_role_headers(jurisdiction_id: str) -> Dict[str, Dict[str, str]]:
    """One usable header set per role of PRD 2.1, keyed by role name.

    The two identity-bearing roles are bound to `jurisdiction_id` so that the
    resulting header sets are usable for ownership-gated calls as well as reads.
    """
    return {
        "RegionalAdministrator": make_regional_administrator_headers(),
        "HazardAnalyst": make_hazard_analyst_headers(),
        "ProjectSponsor": make_project_sponsor_headers(jurisdiction_id),
        "BCAReviewer": make_bca_reviewer_headers(),
        "JurisdictionDelegate": make_jurisdiction_delegate_headers(jurisdiction_id),
        "EquityOfficer": make_equity_officer_headers(),
    }
