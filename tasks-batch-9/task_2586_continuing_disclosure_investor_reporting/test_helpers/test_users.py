"""Pre-built role headers for every role in the PRD (PRD §2.1).

`FinanceDirector`, `DisclosureOfficer` and `ComplianceReviewer` carry an opaque
`X-User-ID` that the server never compares against an entity id, so shared
constants are always correct for them.  Two distinct officers and two distinct
reviewers exist because both segregation-of-duties prohibitions are same-role
prohibitions.

A `DisseminationAgent`'s `X-User-ID` is the `id` of the acting
`DisseminationEngagement` row, so it MUST be built per instance with
`make_agent_headers(engagement_id)`.
"""

from prd_bench_local_runner.testing import build_user_headers

FINANCE_DIRECTOR_ID = "fd-1"
OFFICER_PREPARER_ID = "off-prep"
OFFICER_ASSEMBLER_ID = "off-asm"
REVIEWER_ONE_ID = "rev-1"
REVIEWER_TWO_ID = "rev-2"

TEST_USERS = {
    "finance_director_headers": build_user_headers(FINANCE_DIRECTOR_ID, "FinanceDirector"),
    # The preparer: attests content items and therefore cannot assemble the cycle.
    "disclosure_officer_headers": build_user_headers(OFFICER_PREPARER_ID, "DisclosureOfficer"),
    # A second, distinct officer used for assembly.
    "assembler_officer_headers": build_user_headers(OFFICER_ASSEMBLER_ID, "DisclosureOfficer"),
    # The reviewer of record.
    "compliance_reviewer_headers": build_user_headers(REVIEWER_ONE_ID, "ComplianceReviewer"),
    # A second, distinct reviewer used for posting.
    "second_reviewer_headers": build_user_headers(REVIEWER_TWO_ID, "ComplianceReviewer"),
    # Fallback only for tests that do not exercise agent identity (401/404 probes).
    "dissemination_agent_headers": build_user_headers("agent-not-an-engagement", "DisseminationAgent"),
}


def make_finance_director_headers(user_id: str = FINANCE_DIRECTOR_ID) -> dict:
    return build_user_headers(user_id, "FinanceDirector")


def make_officer_headers(user_id: str = OFFICER_PREPARER_ID) -> dict:
    return build_user_headers(user_id, "DisclosureOfficer")


def make_reviewer_headers(user_id: str = REVIEWER_ONE_ID) -> dict:
    return build_user_headers(user_id, "ComplianceReviewer")


def make_agent_headers(engagement_id: str) -> dict:
    """For DisseminationAgent calls: pass the acting engagement's own `id`.

    Every submit / resubmit / confirm / reject / acknowledge-calendar call
    resolves `X-User-ID` to a stored engagement row, so passing anything other
    than a real engagement id yields ERR_AGENT_NOT_ENGAGED.
    """
    return build_user_headers(engagement_id, "DisseminationAgent")
