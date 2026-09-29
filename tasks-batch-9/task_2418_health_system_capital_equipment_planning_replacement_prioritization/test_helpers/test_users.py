"""Pre-built role headers for the five roles the PRD defines.

Three roles are backed by a persisted entity, and for those three `X-User-ID`
is a resource identifier that ownership checks compare against: a
`ClinicalRequester` acts as a `Department`, a `FacilityDirector` acts as a
`Facility`, and a `CommitteeMember` acts as a `CommitteeMember` row. Any
ownership-gated call MUST therefore be issued with the matching
``make_*_headers(<entity id>)`` builder below.

The two remaining roles are opaque identifiers. Because the planner identity
recorded on an allocation run is barred from funding, two distinct planner
identifiers are provided.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque planner identities. `PLANNER_ALLOC_USER_ID` runs allocations;
# `PLANNER_FUND_USER_ID` draws capital from them.
PLANNER_SETUP_USER_ID = "planner-setup"
PLANNER_ALLOC_USER_ID = "planner-alloc"
PLANNER_FUND_USER_ID = "planner-fund"
AUDITOR_USER_ID = "auditor-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "planner_headers": build_user_headers(PLANNER_SETUP_USER_ID, UserRole.CAPITAL_PLANNER.value),
    "planner_alloc_headers": build_user_headers(
        PLANNER_ALLOC_USER_ID, UserRole.CAPITAL_PLANNER.value
    ),
    "planner_fund_headers": build_user_headers(
        PLANNER_FUND_USER_ID, UserRole.CAPITAL_PLANNER.value
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, UserRole.COMPLIANCE_AUDITOR.value),
    # Entity-backed roles — these shared constants are only safe for calls that
    # do not exercise ownership (role-refusal and not-found probes).
    "requester_headers": build_user_headers(
        "department-not-a-row", UserRole.CLINICAL_REQUESTER.value
    ),
    "director_headers": build_user_headers("facility-not-a-row", UserRole.FACILITY_DIRECTOR.value),
    "member_headers": build_user_headers("member-not-a-row", UserRole.COMMITTEE_MEMBER.value),
}


def make_capital_planner_headers(user_id: str) -> dict:
    """For `CapitalPlanner` (an opaque planner identifier)."""
    return build_user_headers(user_id, UserRole.CAPITAL_PLANNER.value)


def make_clinical_requester_headers(department_id: str) -> dict:
    """For `ClinicalRequester`. Pass the acting `Department.id`."""
    return build_user_headers(department_id, UserRole.CLINICAL_REQUESTER.value)


def make_facility_director_headers(facility_id: str) -> dict:
    """For `FacilityDirector`. Pass the acting `Facility.id`."""
    return build_user_headers(facility_id, UserRole.FACILITY_DIRECTOR.value)


def make_committee_member_headers(member_id: str) -> dict:
    """For `CommitteeMember`. Pass the acting `CommitteeMember.id`."""
    return build_user_headers(member_id, UserRole.COMMITTEE_MEMBER.value)


def make_compliance_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    """For `ComplianceAuditor` (an opaque auditor identifier)."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_AUDITOR.value)


def blank_user_headers(role: str) -> dict:
    """Headers whose `X-User-ID` is blank, for the head-of-ladder identity check."""
    return build_user_headers("", role)
