"""Caller identities for each of the seven program roles.

Two roles are identity-bearing: the ``PropertyOwner``'s ``X-User-ID`` is the
parcel id and the ``Contractor``'s is the contractor id.  Those two therefore
have no fixed constant — a per-entity builder is the only correct form, because
the ownership checks compare the header against the resource's own parcel or
contractor.  The remaining five roles are operator accounts, so a stable
identifier per role is enough.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONTRACTOR,
    ROLE_COUNTY_OFFICER,
    ROLE_FUNDING_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PROPERTY_OWNER,
    ROLE_UNDERWRITING_ANALYST,
)
from .types import Headers, ResourceId

# --- operator accounts ---------------------------------------------------------

PROGRAM_ADMIN_USER_ID = "u_admin"
UNDERWRITING_ANALYST_USER_ID = "u_ana_1"
SECOND_UNDERWRITING_ANALYST_USER_ID = "u_ana_2"
COMPLIANCE_OFFICER_USER_ID = "u_comp_1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "u_comp_2"
# Two distinct funding officers: one verifies the certificate, the other
# releases the funds, because those two acts may not share a user.
FUNDING_OFFICER_VERIFIER_USER_ID = "u_fund_v"
FUNDING_OFFICER_RELEASER_USER_ID = "u_fund_r"
COUNTY_OFFICER_USER_ID = "u_county"

PROGRAM_ADMIN = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
UNDERWRITING_ANALYST = build_user_headers(
    UNDERWRITING_ANALYST_USER_ID, ROLE_UNDERWRITING_ANALYST
)
SECOND_UNDERWRITING_ANALYST = build_user_headers(
    SECOND_UNDERWRITING_ANALYST_USER_ID, ROLE_UNDERWRITING_ANALYST
)
COMPLIANCE_OFFICER = build_user_headers(
    COMPLIANCE_OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
SECOND_COMPLIANCE_OFFICER = build_user_headers(
    SECOND_COMPLIANCE_OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
FUNDING_OFFICER_VERIFIER = build_user_headers(
    FUNDING_OFFICER_VERIFIER_USER_ID, ROLE_FUNDING_OFFICER
)
FUNDING_OFFICER_RELEASER = build_user_headers(
    FUNDING_OFFICER_RELEASER_USER_ID, ROLE_FUNDING_OFFICER
)
COUNTY_OFFICER = build_user_headers(COUNTY_OFFICER_USER_ID, ROLE_COUNTY_OFFICER)


# --- identity-bearing roles ----------------------------------------------------


def owner_headers(property_id: ResourceId) -> Headers:
    """Headers for the homeowner of ``property_id`` (the parcel id is the user id)."""
    return build_user_headers(property_id, ROLE_PROPERTY_OWNER)


def contractor_headers(contractor_id: ResourceId) -> Headers:
    """Headers for ``contractor_id`` acting as itself."""
    return build_user_headers(contractor_id, ROLE_CONTRACTOR)


def headers_for_role(role: str, user_id: str) -> Headers:
    """Arbitrary role/identity pair, for authorization probing."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Headers:
    """A well-formed request that omits ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Headers:
    """A well-formed request that omits ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_role(user_id: str) -> Headers:
    """A request whose ``X-User-Role`` is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


# Convenience map for role-sweep style checks over the operator roles.
OPERATOR_HEADERS_BY_ROLE = {
    ROLE_UNDERWRITING_ANALYST: UNDERWRITING_ANALYST,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    ROLE_FUNDING_OFFICER: FUNDING_OFFICER_VERIFIER,
    ROLE_COUNTY_OFFICER: COUNTY_OFFICER,
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN,
}
