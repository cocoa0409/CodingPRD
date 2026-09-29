"""Pre-built role headers for every role in the PRD (Section 2.1).

`UnderwritingOfficer`, `ComplianceOfficer` and `ClaimsAdjuster` present an
opaque operator identifier, so the shared constants below are the canonical
form for those three roles.

`BuilderPrincipal` and `Homeowner` anchor their identity in a persisted row:
`X-User-ID` must be the acting `Builder.id` / `Homeowner.id`. Ownership-gated
calls MUST therefore use make_builder_principal_headers(builder["id"]) and
make_homeowner_headers(homeowner["id"]); the shared constants for those two
roles are only for tests that deliberately act as a non-owner or that never
reach an ownership check.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, stable across the suite.
UW_OFFICER_USER_ID = "uw-officer-001"
COMPLIANCE_USER_ID = "compliance-001"
ADJUSTER_USER_ID = "adjuster-001"
SECOND_ADJUSTER_USER_ID = "adjuster-002"
THIRD_ADJUSTER_USER_ID = "adjuster-003"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "underwriting_officer_headers": build_user_headers(
        UW_OFFICER_USER_ID, "UnderwritingOfficer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_USER_ID, "ComplianceOfficer"
    ),
    "claims_adjuster_headers": build_user_headers(ADJUSTER_USER_ID, "ClaimsAdjuster"),
    "second_claims_adjuster_headers": build_user_headers(
        SECOND_ADJUSTER_USER_ID, "ClaimsAdjuster"
    ),
    "third_claims_adjuster_headers": build_user_headers(
        THIRD_ADJUSTER_USER_ID, "ClaimsAdjuster"
    ),
    # entity_backed roles: fallbacks for non-ownership tests only.
    "builder_principal_headers": build_user_headers(
        "unowned-builder-principal", "BuilderPrincipal"
    ),
    "homeowner_headers": build_user_headers("unowned-homeowner", "Homeowner"),
}


def make_underwriting_officer_headers(user_id: str = UW_OFFICER_USER_ID
                                      ) -> Dict[str, str]:
    """Opaque operator identity for an UnderwritingOfficer."""
    return build_user_headers(user_id, "UnderwritingOfficer")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_USER_ID
                                    ) -> Dict[str, str]:
    """Opaque operator identity for a ComplianceOfficer."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_claims_adjuster_headers(user_id: str = ADJUSTER_USER_ID) -> Dict[str, str]:
    """Opaque operator identity for a ClaimsAdjuster. The identifier matters:
    it is stamped as adjudicated_by_user_id and outcome_recorded_by_user_id and
    is compared by the segregation-of-duties rule."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_builder_principal_headers(builder_id: str) -> Dict[str, str]:
    """For BuilderPrincipal. Pass the acting Builder.id — ownership checks
    compare the addressed resource's builder foreign key to X-User-ID."""
    return build_user_headers(builder_id, "BuilderPrincipal")


def make_homeowner_headers(homeowner_id: str) -> Dict[str, str]:
    """For Homeowner. Pass the acting Homeowner.id — ownership checks compare
    the addressed policy's current_owner_id to X-User-ID."""
    return build_user_headers(homeowner_id, "Homeowner")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for RBAC and authentication tests."""
    return build_user_headers(user_id, role)
