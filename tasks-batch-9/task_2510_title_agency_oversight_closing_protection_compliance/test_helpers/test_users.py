"""Role headers for the five roles of PRD §2.1.

`AgencyPrincipal` is the one entity-backed identity: "When `X-User-Role` is
`AgencyPrincipal`, `X-User-ID` is the `id` of the acting `Agency`". Ownership-gated
calls MUST therefore build their headers with `make_agency_principal_headers()`
and the real agency id — the shared `agency_principal_headers` constant below is
only for probes that never reach the ownership tier (401/403-by-role and
not-found probes).

The other four roles are opaque operator identifiers, so a module-level constant
is their canonical form. Two distinct identifiers exist for `ComplianceOfficer`
and for `UnderwritingCounsel` because SoD-1 and SoD-2 compare a fresh
`X-User-ID` against a persisted one.
"""

from typing import Dict, List

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1).
LICENSING_ANALYST_USER_ID = "analyst-1"
ESCROW_AUDITOR_USER_ID = "auditor-1"
SECOND_ESCROW_AUDITOR_USER_ID = "auditor-9"
UNDERWRITING_COUNSEL_USER_ID = "counsel-1"
SECOND_UNDERWRITING_COUNSEL_USER_ID = "counsel-2"
COMPLIANCE_OFFICER_USER_ID = "officer-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "officer-2"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "licensing_analyst_headers": build_user_headers(
        LICENSING_ANALYST_USER_ID, "LicensingAnalyst"
    ),
    "escrow_auditor_headers": build_user_headers(
        ESCROW_AUDITOR_USER_ID, "EscrowAuditor"
    ),
    "second_escrow_auditor_headers": build_user_headers(
        SECOND_ESCROW_AUDITOR_USER_ID, "EscrowAuditor"
    ),
    "underwriting_counsel_headers": build_user_headers(
        UNDERWRITING_COUNSEL_USER_ID, "UnderwritingCounsel"
    ),
    "second_underwriting_counsel_headers": build_user_headers(
        SECOND_UNDERWRITING_COUNSEL_USER_ID, "UnderwritingCounsel"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    # Entity-backed role. This constant names no real agency, so it is only
    # usable where the ownership tier is never reached.
    "agency_principal_headers": build_user_headers(
        "unowned-agency-principal", "AgencyPrincipal"
    ),
}


def make_agency_principal_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the `AgencyPrincipal` of one specific agency.

    `X-User-ID` is the acting agency's own `id`, which is what every ownership
    check compares against (PRD §2.1).
    """
    return build_user_headers(agency_id, "AgencyPrincipal")


def make_licensing_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LicensingAnalyst")


def make_escrow_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "EscrowAuditor")


def make_underwriting_counsel_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "UnderwritingCounsel")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


ALL_ROLE_NAMES: List[str] = [
    "AgencyPrincipal",
    "LicensingAnalyst",
    "EscrowAuditor",
    "UnderwritingCounsel",
    "ComplianceOfficer",
]

# "Reads are open. Every list and detail endpoint in Section 4 admits all five
# roles" — these are the opaque four, usable on any read without an agency id.
OPERATOR_READ_HEADERS: List[Dict[str, str]] = [
    TEST_USERS["licensing_analyst_headers"],
    TEST_USERS["escrow_auditor_headers"],
    TEST_USERS["underwriting_counsel_headers"],
    TEST_USERS["compliance_officer_headers"],
]
