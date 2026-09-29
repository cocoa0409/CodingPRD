"""
Pre-built auth headers for every acting identity in the test suite.

PRD section 2.1 splits the seven roles in two. Six of them carry an *opaque*
identity: "`X-User-ID` is an opaque operator identifier that is not tied to
any persisted entity and is never compared against any entity's `id`" — so
the fixed strings below are legitimate operator identifiers for those roles,
and the pairs (``fso-1``/``fso-2``, ``sup-1``/``sup-2``, ``clerk-1``/
``clerk-2``) exist to drive the segregation-of-duties rules of section 2.10.

The seventh role is different: "When `X-User-Role` is `Picker`, `X-User-ID`
is the `id` of the acting `Picker` row". Picker headers therefore cannot be
pre-built and must be minted per picker with ``make_picker_headers``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CREW_SUPERVISOR,
    ROLE_FOOD_SAFETY_OFFICER,
    ROLE_HARVEST_MANAGER,
    ROLE_PACKHOUSE_OPERATOR,
    ROLE_PAYROLL_CLERK,
    ROLE_PICKER,
    ROLE_SALES_MANAGER,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────

HM_1 = "hm-1"
HM_2 = "hm-2"
FSO_1 = "fso-1"
FSO_2 = "fso-2"
SUP_1 = "sup-1"
SUP_2 = "sup-2"
CLERK_1 = "clerk-1"
CLERK_2 = "clerk-2"
PACK_1 = "pack-1"
PACK_2 = "pack-2"
SALES_1 = "sales-1"
SALES_2 = "sales-2"

# ─── Ready-made header dicts ──────────────────────────────────────────────

HARVEST_MANAGER = build_user_headers(HM_1, ROLE_HARVEST_MANAGER)
HARVEST_MANAGER_2 = build_user_headers(HM_2, ROLE_HARVEST_MANAGER)
FOOD_SAFETY_OFFICER = build_user_headers(FSO_1, ROLE_FOOD_SAFETY_OFFICER)
FOOD_SAFETY_OFFICER_2 = build_user_headers(FSO_2, ROLE_FOOD_SAFETY_OFFICER)
CREW_SUPERVISOR = build_user_headers(SUP_1, ROLE_CREW_SUPERVISOR)
CREW_SUPERVISOR_2 = build_user_headers(SUP_2, ROLE_CREW_SUPERVISOR)
PAYROLL_CLERK = build_user_headers(CLERK_1, ROLE_PAYROLL_CLERK)
PAYROLL_CLERK_2 = build_user_headers(CLERK_2, ROLE_PAYROLL_CLERK)
PACKHOUSE_OPERATOR = build_user_headers(PACK_1, ROLE_PACKHOUSE_OPERATOR)
PACKHOUSE_OPERATOR_2 = build_user_headers(PACK_2, ROLE_PACKHOUSE_OPERATOR)
SALES_MANAGER = build_user_headers(SALES_1, ROLE_SALES_MANAGER)
SALES_MANAGER_2 = build_user_headers(SALES_2, ROLE_SALES_MANAGER)

# A clerk operating in the CrewSupervisor capacity. PRD section 2.1 says the
# supervisor identity is compared against "the `supervisor_user_id` value that
# was supplied when the crew was recruited", so a crew recruited with
# supervisor_user_id "clerk-1" is legitimately tallied by this header — which
# is how the tally-versus-approve duty split of section 2.10 is exercised.
CLERK_1_AS_SUPERVISOR = build_user_headers(CLERK_1, ROLE_CREW_SUPERVISOR)

# Reference-only buyer contacts. PRD section 2.1: the `buyer_user_id` "is
# stored for reference only; the API grants no access on the strength of it".
BUYER_USER_IDS = tuple(f"buyer-{n}" for n in range(1, 41))


def make_picker_headers(picker_id: str) -> Dict[str, str]:
    """Auth headers for the entity-backed `Picker` role (PRD 2.1)."""
    return build_user_headers(picker_id, ROLE_PICKER)


def headers_with_role(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/id pair, for authentication and authorization probes."""
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = HM_1) -> Dict[str, str]:
    """Headers that omit `X-User-Role` entirely (PRD 2.7 rule 1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_HARVEST_MANAGER) -> Dict[str, str]:
    """Headers that omit `X-User-ID` entirely (PRD 2.7 rule 1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_HARVEST_MANAGER) -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but empty (PRD 2.7 rule 1)."""
    return build_user_headers("", role)


def headers_undeclared_role(user_id: str = HM_1) -> Dict[str, str]:
    """Headers naming a role outside the seven declared names (PRD 2.7 rule 2)."""
    return build_user_headers(user_id, "FieldBoss")


# Convenience: the role lists of PRD section 4, keyed by the capability they
# guard, for cross-role forbidden probes.
ALL_OPAQUE_HEADERS = {
    ROLE_HARVEST_MANAGER: HARVEST_MANAGER,
    ROLE_FOOD_SAFETY_OFFICER: FOOD_SAFETY_OFFICER,
    ROLE_CREW_SUPERVISOR: CREW_SUPERVISOR,
    ROLE_PAYROLL_CLERK: PAYROLL_CLERK,
    ROLE_PACKHOUSE_OPERATOR: PACKHOUSE_OPERATOR,
    ROLE_SALES_MANAGER: SALES_MANAGER,
}

__all__ = [
    "HM_1",
    "HM_2",
    "FSO_1",
    "FSO_2",
    "SUP_1",
    "SUP_2",
    "CLERK_1",
    "CLERK_2",
    "PACK_1",
    "PACK_2",
    "SALES_1",
    "SALES_2",
    "HARVEST_MANAGER",
    "HARVEST_MANAGER_2",
    "FOOD_SAFETY_OFFICER",
    "FOOD_SAFETY_OFFICER_2",
    "CREW_SUPERVISOR",
    "CREW_SUPERVISOR_2",
    "PAYROLL_CLERK",
    "PAYROLL_CLERK_2",
    "PACKHOUSE_OPERATOR",
    "PACKHOUSE_OPERATOR_2",
    "SALES_MANAGER",
    "SALES_MANAGER_2",
    "CLERK_1_AS_SUPERVISOR",
    "BUYER_USER_IDS",
    "ROLE_PICKER",
    "make_picker_headers",
    "headers_with_role",
    "headers_missing_role",
    "headers_missing_user_id",
    "headers_empty_user_id",
    "headers_undeclared_role",
    "ALL_OPAQUE_HEADERS",
]
