"""Identity headers for the five roles.

The three opaque roles (`RegulatoryReviewer`, `EnforcementOfficer`,
`SystemOperator`) carry an operator identifier the server never compares to a
stored entity, so fixed labels are used for them. The two entity-backed roles
must present the primary key of the resource they act as: a
`FacilityRegistrant` presents the acting facility's `id` and a
`ResponsiblePersonAgent` presents the acting responsible person's `id`, so
their headers are always built per entity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ENFORCEMENT_OFFICER,
    ROLE_FACILITY_REGISTRANT,
    ROLE_REGULATORY_REVIEWER,
    ROLE_RESPONSIBLE_PERSON_AGENT,
    ROLE_SYSTEM_OPERATOR,
)

# Opaque operator identifiers.
REVIEWER_1 = "RVW-1"
REVIEWER_2 = "RVW-2"
OFFICER_1 = "OFF-1"
OFFICER_2 = "OFF-2"
OPERATOR_1 = "OPS-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "reviewer": build_user_headers(REVIEWER_1, ROLE_REGULATORY_REVIEWER),
    "reviewer_2": build_user_headers(REVIEWER_2, ROLE_REGULATORY_REVIEWER),
    "officer": build_user_headers(OFFICER_1, ROLE_ENFORCEMENT_OFFICER),
    "officer_2": build_user_headers(OFFICER_2, ROLE_ENFORCEMENT_OFFICER),
    "operator": build_user_headers(OPERATOR_1, ROLE_SYSTEM_OPERATOR),
}

REVIEWER_HEADERS = TEST_USERS["reviewer"]
REVIEWER_2_HEADERS = TEST_USERS["reviewer_2"]
OFFICER_HEADERS = TEST_USERS["officer"]
OFFICER_2_HEADERS = TEST_USERS["officer_2"]
OPERATOR_HEADERS = TEST_USERS["operator"]


def make_facility_registrant_headers(facility_id: str) -> Dict[str, str]:
    """Headers for the registrant of record of the given facility."""
    return build_user_headers(facility_id, ROLE_FACILITY_REGISTRANT)


def make_responsible_person_agent_headers(responsible_person_id: str) -> Dict[str, str]:
    """Headers for the agent of the given responsible person."""
    return build_user_headers(responsible_person_id, ROLE_RESPONSIBLE_PERSON_AGENT)


def make_reviewer_headers(user_id: str = REVIEWER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REGULATORY_REVIEWER)


def make_officer_headers(user_id: str = OFFICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ENFORCEMENT_OFFICER)


def make_operator_headers(user_id: str = OPERATOR_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SYSTEM_OPERATOR)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that carry a role but no acting principal."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that carry a principal but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role that is not one of the five role names."""
    return build_user_headers(user_id, "CosmeticsAuditor")
