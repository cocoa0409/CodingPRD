"""Pre-built role headers for every role the PRD declares.

The PRD identifies the caller with `X-User-ID` and `X-User-Role`. Four of the
five roles are plain operator roles whose user id is opaque, so a shared
constant is the canonical form. `NamedExecutiveOfficer` is different: its
`X-User-ID` must be the id of the Executive row the caller is, because the
officer may only read and acknowledge rows belonging to that executive. Any
ownership-gated officer call MUST therefore use
`make_named_executive_officer_headers(executive["id"])`.

The segregation-of-duties rules also require two DISTINCT user ids inside the
same role, so named constants are provided for the second chair and the second
counsel.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct user ids inside a single role, needed by the segregation-of-duties rules.
CONSULTANT_ONE = "consultant-001"
CONSULTANT_TWO = "consultant-002"
CHAIR_ONE = "chair-001"
CHAIR_TWO = "chair-002"
COUNSEL_ONE = "counsel-001"
COUNSEL_TWO = "counsel-002"
IR_ONE = "ir-001"
IR_TWO = "ir-002"

TEST_USERS = {
    "comp_consultant_headers": build_user_headers(CONSULTANT_ONE, "CompConsultant"),
    "comp_committee_chair_headers": build_user_headers(CHAIR_ONE, "CompCommitteeChair"),
    "securities_counsel_headers": build_user_headers(COUNSEL_ONE, "SecuritiesCounsel"),
    "investor_relations_lead_headers": build_user_headers(IR_ONE, "InvestorRelationsLead"),
    # Fallback only — never use for an ownership-gated officer call.
    "named_executive_officer_headers": build_user_headers(
        "officer-001", "NamedExecutiveOfficer"
    ),
}


def make_comp_consultant_headers(user_id: str) -> dict:
    """Headers for a specific CompConsultant user id."""
    return build_user_headers(user_id, "CompConsultant")


def make_comp_committee_chair_headers(user_id: str) -> dict:
    """Headers for a specific CompCommitteeChair user id.

    Use two different ids when a scenario must satisfy (or breach) the rule that
    the chair who adjusted a goal may not certify its result.
    """
    return build_user_headers(user_id, "CompCommitteeChair")


def make_securities_counsel_headers(user_id: str) -> dict:
    """Headers for a specific SecuritiesCounsel user id.

    Use two different ids when a scenario must satisfy (or breach) the rule that
    the counsel who authored a section may not clear it.
    """
    return build_user_headers(user_id, "SecuritiesCounsel")


def make_investor_relations_lead_headers(user_id: str) -> dict:
    """Headers for a specific InvestorRelationsLead user id."""
    return build_user_headers(user_id, "InvestorRelationsLead")


def make_named_executive_officer_headers(executive_id: str) -> dict:
    """Headers for the officer who IS the given Executive row.

    `executive_id` must be the actual `Executive.id`; the officer's ownership
    checks compare the caller's user id against the executive on the award or
    determination being touched.
    """
    return build_user_headers(executive_id, "NamedExecutiveOfficer")


CONSULTANT = TEST_USERS["comp_consultant_headers"]
CHAIR = TEST_USERS["comp_committee_chair_headers"]
COUNSEL = TEST_USERS["securities_counsel_headers"]
IR_LEAD = TEST_USERS["investor_relations_lead_headers"]
CHAIR_TWO_HEADERS = build_user_headers(CHAIR_TWO, "CompCommitteeChair")
COUNSEL_TWO_HEADERS = build_user_headers(COUNSEL_TWO, "SecuritiesCounsel")
