"""Pre-built role headers for every role in the PRD.

For ``MarketAnalyst``, ``ExaminerInCharge``, ``SupervisingExaminer`` and
``MultistateCoordinator`` the ``X-User-ID`` header is an opaque operator
identifier that is never compared to any entity's ``id``, so the shared
constants below are the canonical form.  For ``InsurerRespondent`` the
``X-User-ID`` header is the ``id`` of the acting carrier, so ownership-gated
calls MUST use :func:`make_insurer_respondent_headers` with the real
``Insurer.id``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque departmental operator identifiers.
MARKET_ANALYST_ID = "44444444-4444-4444-4444-444444444444"
EXAMINER_IN_CHARGE_ID = "33333333-3333-3333-3333-333333333333"
SUPERVISING_EXAMINER_ID = "11111111-1111-1111-1111-111111111111"
# A second supervising examiner: needed wherever the segregation-of-duties
# comparison requires a different operator from the one who set the record up.
SUPERVISING_EXAMINER_B_ID = "22222222-2222-2222-2222-222222222222"
MULTISTATE_COORDINATOR_ID = "55555555-5555-5555-5555-555555555555"
# A second examiner in charge, for tests that need two distinct issuers.
EXAMINER_IN_CHARGE_B_ID = "66666666-6666-6666-6666-666666666666"

TEST_USERS = {
    "market_analyst_headers": build_user_headers(MARKET_ANALYST_ID, "MarketAnalyst"),
    "examiner_in_charge_headers": build_user_headers(
        EXAMINER_IN_CHARGE_ID, "ExaminerInCharge"
    ),
    "examiner_in_charge_b_headers": build_user_headers(
        EXAMINER_IN_CHARGE_B_ID, "ExaminerInCharge"
    ),
    "supervising_examiner_headers": build_user_headers(
        SUPERVISING_EXAMINER_ID, "SupervisingExaminer"
    ),
    "supervising_examiner_b_headers": build_user_headers(
        SUPERVISING_EXAMINER_B_ID, "SupervisingExaminer"
    ),
    "multistate_coordinator_headers": build_user_headers(
        MULTISTATE_COORDINATOR_ID, "MultistateCoordinator"
    ),
    # Fallback only — never use for a carrier write or read that is ownership
    # gated; use make_insurer_respondent_headers(insurer["id"]) instead.
    "insurer_respondent_headers": build_user_headers(
        "77777777-7777-7777-7777-777777777777", "InsurerRespondent"
    ),
}


def make_insurer_respondent_headers(insurer_id: str) -> dict:
    """Headers for the carrier's compliance officer.

    ``insurer_id`` must be the acting ``Insurer.id``: ownership checks walk up
    to the owning examination and compare its ``insurer_id`` to ``X-User-ID``.
    """
    return build_user_headers(insurer_id, "InsurerRespondent")


def make_market_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketAnalyst")


def make_examiner_in_charge_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExaminerInCharge")


def make_supervising_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupervisingExaminer")


def make_multistate_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MultistateCoordinator")


ANALYST = TEST_USERS["market_analyst_headers"]
EIC = TEST_USERS["examiner_in_charge_headers"]
EIC_B = TEST_USERS["examiner_in_charge_b_headers"]
SUPERVISOR = TEST_USERS["supervising_examiner_headers"]
SUPERVISOR_B = TEST_USERS["supervising_examiner_b_headers"]
COORDINATOR = TEST_USERS["multistate_coordinator_headers"]

ALL_ROLE_HEADERS = {
    "MarketAnalyst": ANALYST,
    "ExaminerInCharge": EIC,
    "SupervisingExaminer": SUPERVISOR,
    "MultistateCoordinator": COORDINATOR,
    "InsurerRespondent": TEST_USERS["insurer_respondent_headers"],
}
