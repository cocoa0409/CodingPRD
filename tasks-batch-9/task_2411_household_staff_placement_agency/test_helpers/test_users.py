"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Segregation-of-duties actor ids (PRD §2.10). A reference is recorded by one
# vetting specialist and verified by another; an enforcement case is opened by
# one compliance officer and resolved by another. These ids are load bearing.
VETTING_RECORDER_USER_ID = "u_vet_1"
VETTING_VERIFIER_USER_ID = "u_vet_2"
COMPLIANCE_OPENER_USER_ID = "u_comp_1"
COMPLIANCE_RESOLVER_USER_ID = "u_comp_2"

# Shared constants. Safe for the five opaque roles, and for tests that do not
# exercise resource ownership (bad payloads, missing resources, role refusals).
TEST_USERS = {
    # opaque roles: the shared constant is the canonical form.
    "agency_principal_headers": build_user_headers("u_principal_1", "AgencyPrincipal"),
    "placement_consultant_headers": build_user_headers(
        "u_consultant_1", "PlacementConsultant"
    ),
    "vetting_specialist_headers": build_user_headers(
        VETTING_RECORDER_USER_ID, "VettingSpecialist"
    ),
    "vetting_verifier_headers": build_user_headers(
        VETTING_VERIFIER_USER_ID, "VettingSpecialist"
    ),
    "billing_administrator_headers": build_user_headers(
        "u_billing_1", "BillingAdministrator"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OPENER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_resolver_headers": build_user_headers(
        COMPLIANCE_RESOLVER_USER_ID, "ComplianceOfficer"
    ),
    # entity_backed roles: the shared constant is a fallback for tests that do
    # not depend on the caller owning the subject resource. Ownership-gated
    # calls MUST use make_client_headers / make_candidate_headers instead.
    "client_headers": build_user_headers("u_client_placeholder", "Client"),
    "candidate_headers": build_user_headers("u_candidate_placeholder", "Candidate"),
}


# --- Per-instance builders: required for every entity_backed role ------------


def make_client_headers(user_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Client")


def make_candidate_headers(user_id: str) -> dict:
    """For the Candidate role (entity_backed:Candidate). Pass the actual
    Candidate.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Candidate")


# --- Per-instance builders for the opaque roles, for duty-segregation tests --


def make_vetting_specialist_headers(user_id: str) -> dict:
    """A named VettingSpecialist. The recorder of a reference and its verifier
    must be different users."""
    return build_user_headers(user_id, "VettingSpecialist")


def make_compliance_officer_headers(user_id: str) -> dict:
    """A named ComplianceOfficer. The opener of an enforcement case and its
    resolver must be different users."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_agency_principal_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyPrincipal")


def make_placement_consultant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlacementConsultant")


def make_billing_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAdministrator")


# Every role name the API recognises, in the order given by PRD §4.
ALL_ROLE_NAMES = (
    "AgencyPrincipal",
    "PlacementConsultant",
    "VettingSpecialist",
    "BillingAdministrator",
    "ComplianceOfficer",
    "Client",
    "Candidate",
)
