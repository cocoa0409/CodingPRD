"""Pre-built role headers for every role in PRD §2.1.

The five opaque roles (SystemAdmin, SponsoredProgramsOfficer, GrantCoordinator,
GrantsAccountant, SponsorOfficial) use shared constants: their X-User-ID is an
opaque operator identifier never compared to an entity id.

The two entity-backed roles (PrincipalInvestigator, ResearchStaff) MUST be built
per-instance via make_*_headers(person_id): their X-User-ID is the id of the
acting Person, and ownership checks compare it against the resource's
person_id / pi_id. Using the shared constant for an entity-backed role on an
ownership-gated call would always fail the ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import OPERATOR_IDS

TEST_USERS = {
    "system_admin_headers": build_user_headers(OPERATOR_IDS["ADMIN_1"], "SystemAdmin"),
    "spo_headers": build_user_headers(OPERATOR_IDS["OFFICER_1"], "SponsoredProgramsOfficer"),
    "coordinator_headers": build_user_headers(OPERATOR_IDS["COORDINATOR_1"], "GrantCoordinator"),
    "accountant_headers": build_user_headers(OPERATOR_IDS["ACCOUNTANT_1"], "GrantsAccountant"),
    "accountant_2_headers": build_user_headers(OPERATOR_IDS["ACCOUNTANT_2"], "GrantsAccountant"),
    "accountant_9_headers": build_user_headers(OPERATOR_IDS["ACCOUNTANT_9"], "GrantsAccountant"),
    "sponsor_official_headers": build_user_headers(OPERATOR_IDS["SPONSOR_1"], "SponsorOfficial"),
    # Fallback constants for the entity-backed roles — only safe on calls that
    # do NOT exercise ownership (e.g., plain GETs). Ownership-gated calls
    # (certify, PI report submit) must use the builders below.
    "pi_headers": build_user_headers("test-pi-1", "PrincipalInvestigator"),
    "staff_headers": build_user_headers("test-staff-1", "ResearchStaff"),
}


def make_pi_headers(person_id: str) -> dict:
    """PrincipalInvestigator is entity-backed: X-User-ID must be the Person.id
    whenever the call is ownership-gated (statement certify, report submit)."""
    return build_user_headers(person_id, "PrincipalInvestigator")


def make_research_staff_headers(person_id: str) -> dict:
    """ResearchStaff is entity-backed: X-User-ID must be the Person.id
    whenever the call is ownership-gated (statement certify)."""
    return build_user_headers(person_id, "ResearchStaff")
