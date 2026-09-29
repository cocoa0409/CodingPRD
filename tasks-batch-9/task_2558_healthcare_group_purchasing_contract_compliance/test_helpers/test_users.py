"""Acting identities and their header builders.

The PRD states that every request carries two mandatory HTTP headers: `X-User-ID`
identifies the acting user and `X-User-Role` declares the operational capacity in
which that user is acting.  Two roles need *pairs* of distinct users because the
API enforces segregation of duties:

* ``ContractManager`` — the local-exception approver may not be the endorser.
* ``ClinicalReviewer`` — the evidence endorser/rejecter may not be the submitter.

``MemberMaterialsManager`` is different in kind: that role is backed by a Member
row, so the acting user id must be the real ``Member.id`` of the member whose
data is being touched.  Never invent an id for that role — thread the created
member's id through ``make_member_materials_manager_headers``.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLINICAL_REVIEWER,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_CONTRACT_MANAGER,
    ROLE_DISTRIBUTOR_AGENT,
    ROLE_FINANCE_ADMINISTRATOR,
    ROLE_MEMBER_MATERIALS_MANAGER,
)

# --- canonical user identifiers -------------------------------------------

CONTRACT_MANAGER_1 = "CM-1"
CONTRACT_MANAGER_2 = "CM-2"
CLINICAL_REVIEWER_1 = "CR-1"
CLINICAL_REVIEWER_2 = "CR-2"
COMPLIANCE_ANALYST_1 = "U-OPS-1"
DISTRIBUTOR_AGENT_1 = "U-DIST-1"
FINANCE_ADMINISTRATOR_1 = "U-FIN-1"

# A syntactically valid identifier that is not any member's id, for probing the
# entity-backed role from an identity that owns nothing.
UNOWNED_MEMBER_USER_ID = "00000000-0000-0000-0000-0000000000ee"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "contract_manager": {
        "user_id": CONTRACT_MANAGER_1,
        "role": ROLE_CONTRACT_MANAGER,
    },
    "contract_manager_2": {
        "user_id": CONTRACT_MANAGER_2,
        "role": ROLE_CONTRACT_MANAGER,
    },
    "clinical_reviewer": {
        "user_id": CLINICAL_REVIEWER_1,
        "role": ROLE_CLINICAL_REVIEWER,
    },
    "clinical_reviewer_2": {
        "user_id": CLINICAL_REVIEWER_2,
        "role": ROLE_CLINICAL_REVIEWER,
    },
    "compliance_analyst": {
        "user_id": COMPLIANCE_ANALYST_1,
        "role": ROLE_COMPLIANCE_ANALYST,
    },
    "distributor_agent": {
        "user_id": DISTRIBUTOR_AGENT_1,
        "role": ROLE_DISTRIBUTOR_AGENT,
    },
    "finance_administrator": {
        "user_id": FINANCE_ADMINISTRATOR_1,
        "role": ROLE_FINANCE_ADMINISTRATOR,
    },
}


# --- header builders -------------------------------------------------------


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Explicit role/identity pair, for cross-role probes."""
    return build_user_headers(user_id, role)


def contract_manager_headers(user_id: str = CONTRACT_MANAGER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CONTRACT_MANAGER)


def contract_manager_2_headers() -> Dict[str, str]:
    return build_user_headers(CONTRACT_MANAGER_2, ROLE_CONTRACT_MANAGER)


def clinical_reviewer_headers(user_id: str = CLINICAL_REVIEWER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CLINICAL_REVIEWER)


def clinical_reviewer_2_headers() -> Dict[str, str]:
    return build_user_headers(CLINICAL_REVIEWER_2, ROLE_CLINICAL_REVIEWER)


def compliance_analyst_headers(user_id: str = COMPLIANCE_ANALYST_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_ANALYST)


def distributor_agent_headers(user_id: str = DISTRIBUTOR_AGENT_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DISTRIBUTOR_AGENT)


def finance_administrator_headers(
    user_id: str = FINANCE_ADMINISTRATOR_1,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FINANCE_ADMINISTRATOR)


def make_member_materials_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for the entity-backed role.

    ``user_id`` MUST be the ``Member.id`` returned when the member was created;
    the server resolves member ownership from this header value.
    """
    return build_user_headers(user_id, ROLE_MEMBER_MATERIALS_MANAGER)


def anonymous_headers(role: Optional[str] = ROLE_CONTRACT_MANAGER) -> Dict[str, str]:
    """Headers that declare a role but carry no acting user identity."""
    headers = build_user_headers("", role or ROLE_CONTRACT_MANAGER)
    headers["X-User-ID"] = ""
    return headers


def roleless_headers(user_id: str = CONTRACT_MANAGER_1) -> Dict[str, str]:
    """Headers that carry an identity but declare no operational capacity."""
    headers = build_user_headers(user_id, "")
    headers["X-User-Role"] = ""
    return headers
