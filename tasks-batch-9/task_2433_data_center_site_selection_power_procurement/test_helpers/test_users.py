"""Pre-built role headers for the six roles of §2.1.

Five of the six roles carry an opaque operator identifier that the server "never
compares to any entity's `id`", so a shared constant per role is the canonical
form for them — with extra distinct identifiers where a test needs two different
operators for the segregation-of-duties comparisons of §2.9.

``UtilityPlanner`` is different: §2.1 states that ``X-User-ID`` is "the `id` of
the acting `Utility`", so every ownership-gated planner call — a capacity
revision, a load study, a capacity reservation, an energization commitment —
MUST be made with ``make_utility_planner_headers(utility["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. ``user_analyst_1`` screens sites, so
# ``user_chair_1`` is the operator that may legitimately commit them; likewise
# ``user_negotiator_1`` signs term sheets and ``user_chair_1`` ratifies them.
ANALYST_USER_ID = "user_analyst_1"
ANALYST_2_USER_ID = "user_analyst_2"
DIRECTOR_USER_ID = "user_director_1"
NEGOTIATOR_USER_ID = "user_negotiator_1"
AUTHORITY_USER_ID = "user_authority_1"
CHAIR_USER_ID = "user_chair_1"
CHAIR_2_USER_ID = "user_chair_2"

TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "SiteScreeningAnalyst"),
    "analyst_2_headers": build_user_headers(ANALYST_2_USER_ID, "SiteScreeningAnalyst"),
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "PortfolioDirector"),
    "negotiator_headers": build_user_headers(NEGOTIATOR_USER_ID, "IncentiveNegotiator"),
    "authority_headers": build_user_headers(AUTHORITY_USER_ID, "PermittingAuthority"),
    "chair_headers": build_user_headers(CHAIR_USER_ID, "CapitalCommitteeChair"),
    "chair_2_headers": build_user_headers(CHAIR_2_USER_ID, "CapitalCommitteeChair"),
    # Entity-backed role: this shared constant is only for calls that never pass
    # a utility identity check (wrong-role cases, unknown-path cases and the
    # deliberate ERR_UTILITY_IDENTITY_MISMATCH cases).
    "utility_planner_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "UtilityPlanner"
    ),
}


def make_utility_planner_headers(utility_id: str) -> dict:
    """Headers for a ``UtilityPlanner`` acting as the given ``Utility``.

    Pass the real ``Utility.id``: §2.1 binds ``X-User-ID`` to the acting
    utility's identifier, and the same identifier is stamped onto a load study
    as ``filed_by_user_id``.
    """
    return build_user_headers(utility_id, "UtilityPlanner")


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "SiteScreeningAnalyst")


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> dict:
    return build_user_headers(user_id, "PortfolioDirector")


def make_negotiator_headers(user_id: str = NEGOTIATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "IncentiveNegotiator")


def make_authority_headers(user_id: str = AUTHORITY_USER_ID) -> dict:
    return build_user_headers(user_id, "PermittingAuthority")


def make_chair_headers(user_id: str = CHAIR_USER_ID) -> dict:
    """Headers for a ``CapitalCommitteeChair``.

    Pass the screener's or the signer's identifier to drive the
    segregation-of-duties rejections of §2.9.
    """
    return build_user_headers(user_id, "CapitalCommitteeChair")


ALL_ROLE_NAMES = [
    "SiteScreeningAnalyst",
    "PortfolioDirector",
    "UtilityPlanner",
    "IncentiveNegotiator",
    "CapitalCommitteeChair",
    "PermittingAuthority",
]
