"""Pre-built role headers for every role in the PRD (§2.1).

PRD §2.1: when `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the
acting `Claimant` row, so any ownership-gated call must be made with
`make_claimant_headers(<the real Claimant id>)`. The other four roles carry an
opaque operator identifier that is never resolved against a `Claimant` row, so
their shared constants below are the canonical form — but the identifier values
still matter, because §2.12 compares them across operations.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1). Distinct per role so that the
# segregation-of-duties comparison of §2.12 has something to compare.
ANALYST_USER_ID = "u-analyst-1"
ANALYST_USER_ID_ALT = "u-analyst-2"
HEARING_USER_ID = "u-hearing-1"
HEARING_USER_ID_ALT = "u-hearing-2"
DECIDER_USER_ID = "u-decider-1"
DECIDER_USER_ID_ALT = "u-decider-2"
ADJUDICATOR_USER_ID = "u-adjudicator-1"

# A Claimant identifier that deliberately matches no persisted Claimant row.
UNOWNED_CLAIMANT_USER_ID = "00000000-0000-0000-0000-0000000000ff"

TEST_USERS = {
    # entity_backed role: this shared constant is only safe for tests that do
    # NOT exercise ownership (e.g. 401/403/404 probes).
    "claimant_headers": build_user_headers(UNOWNED_CLAIMANT_USER_ID, "Claimant"),
    # opaque roles: the shared constant is the canonical form.
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "WaterRightsAnalyst"),
    "analyst_alt_headers": build_user_headers(
        ANALYST_USER_ID_ALT, "WaterRightsAnalyst"
    ),
    "hearing_officer_headers": build_user_headers(HEARING_USER_ID, "HearingOfficer"),
    "hearing_officer_alt_headers": build_user_headers(
        HEARING_USER_ID_ALT, "HearingOfficer"
    ),
    "decision_authority_headers": build_user_headers(
        DECIDER_USER_ID, "DecisionAuthority"
    ),
    "decision_authority_alt_headers": build_user_headers(
        DECIDER_USER_ID_ALT, "DecisionAuthority"
    ),
    "basin_adjudicator_headers": build_user_headers(
        ADJUDICATOR_USER_ID, "BasinAdjudicator"
    ),
}


def make_claimant_headers(claimant_id: str) -> dict:
    """Headers for the `Claimant` role.

    Pass the real `Claimant.id`: PRD §2.1 compares the resource's claimant
    reference to `X-User-ID` on every ownership-gated call.
    """
    return build_user_headers(claimant_id, "Claimant")


def make_analyst_headers(user_id: str) -> dict:
    """Headers for `WaterRightsAnalyst` with an explicit operator identifier."""
    return build_user_headers(user_id, "WaterRightsAnalyst")


def make_hearing_officer_headers(user_id: str) -> dict:
    """Headers for `HearingOfficer` with an explicit operator identifier."""
    return build_user_headers(user_id, "HearingOfficer")


def make_decision_authority_headers(user_id: str) -> dict:
    """Headers for `DecisionAuthority` with an explicit operator identifier."""
    return build_user_headers(user_id, "DecisionAuthority")


def make_basin_adjudicator_headers(user_id: str) -> dict:
    """Headers for `BasinAdjudicator` with an explicit operator identifier."""
    return build_user_headers(user_id, "BasinAdjudicator")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary (user_id, role) pair."""
    return build_user_headers(user_id, role)


# Headers keyed by role name, for parametrized role-matrix tests.
HEADERS_BY_ROLE = {
    "Claimant": TEST_USERS["claimant_headers"],
    "WaterRightsAnalyst": TEST_USERS["analyst_headers"],
    "HearingOfficer": TEST_USERS["hearing_officer_headers"],
    "DecisionAuthority": TEST_USERS["decision_authority_headers"],
    "BasinAdjudicator": TEST_USERS["basin_adjudicator_headers"],
}
