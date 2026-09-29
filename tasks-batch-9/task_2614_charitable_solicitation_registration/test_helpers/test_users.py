"""Pre-built auth headers for every role the PRD declares.

Two of the five roles are entity-backed: under `CertifyingOfficer` the
`X-User-ID` is the id of an `OfficerDisclosure` row, and under
`FundraiserAgent` it is the id of a `ProfessionalFundraiser` row. Any
ownership-gated call for those roles MUST use the per-instance builders below
with the real entity id; the shared constants are only safe where ownership is
not what the test exercises.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: the shared constant is the canonical form.
    "compliance_officer_headers": build_user_headers(
        "operator-compliance-1", UserRole.COMPLIANCE_OFFICER.value
    ),
    "state_regulator_headers": build_user_headers(
        "operator-regulator-1", UserRole.STATE_REGULATOR.value
    ),
    "system_admin_headers": build_user_headers(
        "operator-admin-1", UserRole.SYSTEM_ADMIN.value
    ),
    # Entity-backed roles: fallback only for tests that do not exercise ownership.
    "certifying_officer_headers": build_user_headers(
        "officer-not-persisted-1", UserRole.CERTIFYING_OFFICER.value
    ),
    "fundraiser_agent_headers": build_user_headers(
        "fundraiser-not-persisted-1", UserRole.FUNDRAISER_AGENT.value
    ),
}


def make_compliance_officer_headers(user_id: str = "operator-compliance-1") -> Dict[str, str]:
    """ComplianceOfficer is opaque; the identifier is never compared to a row."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_state_regulator_headers(user_id: str = "operator-regulator-1") -> Dict[str, str]:
    """StateRegulator is opaque; the identifier is never compared to a row."""
    return build_user_headers(user_id, UserRole.STATE_REGULATOR.value)


def make_system_admin_headers(user_id: str = "operator-admin-1") -> Dict[str, str]:
    """SystemAdmin is opaque; the identifier is never compared to a row."""
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def make_certifying_officer_headers(officer_disclosure_id: str) -> Dict[str, str]:
    """For CertifyingOfficer. Pass the acting OfficerDisclosure's own id."""
    return build_user_headers(officer_disclosure_id, UserRole.CERTIFYING_OFFICER.value)


def make_fundraiser_agent_headers(fundraiser_id: str) -> Dict[str, str]:
    """For FundraiserAgent. Pass the acting ProfessionalFundraiser's own id."""
    return build_user_headers(fundraiser_id, UserRole.FUNDRAISER_AGENT.value)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)
