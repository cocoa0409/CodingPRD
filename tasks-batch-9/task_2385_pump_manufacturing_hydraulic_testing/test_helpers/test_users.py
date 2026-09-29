"""Pre-built authentication headers for every role in the contract.

PRD 2.1: every request carries `X-User-ID` and `X-User-Role`.  Seven of the
eight roles have opaque identities, so a fixed user id per role is enough.
`FoundryPartner` is different: its `X-User-ID` resolves to exactly one Foundry
row, so callers must build its headers from a real foundry id using
`make_foundry_partner_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ── Fixed user identities for the opaque roles ───────────────────────────────
ADMIN_USER_ID = "admin-001"
ENGINEER_USER_ID = "eng-101"
SECOND_ENGINEER_USER_ID = "eng-102"
APPROVER_USER_ID = "appr-201"
SECOND_APPROVER_USER_ID = "appr-202"
INSPECTOR_USER_ID = "qi-301"
SECOND_INSPECTOR_USER_ID = "qi-302"
TEST_ENGINEER_USER_ID = "te-501"
PLANNER_USER_ID = "pp-601"
ADJUDICATOR_USER_ID = "adj-401"
SECOND_ADJUDICATOR_USER_ID = "adj-402"


PLATFORM_ADMIN = build_user_headers(ADMIN_USER_ID, Role.PLATFORM_ADMIN)
APPLICATION_ENGINEER = build_user_headers(ENGINEER_USER_ID, Role.APPLICATION_ENGINEER)
OTHER_APPLICATION_ENGINEER = build_user_headers(
    SECOND_ENGINEER_USER_ID, Role.APPLICATION_ENGINEER
)
HYDRAULIC_APPROVER = build_user_headers(APPROVER_USER_ID, Role.HYDRAULIC_APPROVER)
OTHER_HYDRAULIC_APPROVER = build_user_headers(
    SECOND_APPROVER_USER_ID, Role.HYDRAULIC_APPROVER
)
QUALITY_INSPECTOR = build_user_headers(INSPECTOR_USER_ID, Role.QUALITY_INSPECTOR)
OTHER_QUALITY_INSPECTOR = build_user_headers(
    SECOND_INSPECTOR_USER_ID, Role.QUALITY_INSPECTOR
)
TEST_ENGINEER = build_user_headers(TEST_ENGINEER_USER_ID, Role.TEST_ENGINEER)
PRODUCTION_PLANNER = build_user_headers(PLANNER_USER_ID, Role.PRODUCTION_PLANNER)
WARRANTY_ADJUDICATOR = build_user_headers(
    ADJUDICATOR_USER_ID, Role.WARRANTY_ADJUDICATOR
)
OTHER_WARRANTY_ADJUDICATOR = build_user_headers(
    SECOND_ADJUDICATOR_USER_ID, Role.WARRANTY_ADJUDICATOR
)


def make_foundry_partner_headers(foundry_id: str) -> Dict[str, str]:
    """Headers for the foundry partner whose identity resolves to `foundry_id`.

    PRD 2.1: the foundry partner's user id is the identifier of the Foundry row
    that backs it, and every write is scoped to that foundry's own patterns and
    lots.  Never share one foundry partner header dict across two foundries.
    """
    return build_user_headers(foundry_id, Role.FOUNDRY_PARTNER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user id / role pair, for identity-sensitive scenarios."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that carry a role but no user id."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that carry a user id but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


# Every role except FoundryPartner, whose headers depend on a live foundry id.
HEADERS_BY_ROLE = {
    Role.PLATFORM_ADMIN: PLATFORM_ADMIN,
    Role.APPLICATION_ENGINEER: APPLICATION_ENGINEER,
    Role.HYDRAULIC_APPROVER: HYDRAULIC_APPROVER,
    Role.QUALITY_INSPECTOR: QUALITY_INSPECTOR,
    Role.TEST_ENGINEER: TEST_ENGINEER,
    Role.PRODUCTION_PLANNER: PRODUCTION_PLANNER,
    Role.WARRANTY_ADJUDICATOR: WARRANTY_ADJUDICATOR,
}
