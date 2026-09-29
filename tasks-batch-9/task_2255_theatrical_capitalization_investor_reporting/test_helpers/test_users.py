"""
Acting identities for the five roles.

Four of the five roles are operator roles whose `X-User-ID` "is an opaque
operator identifier that is not tied to any persisted entity"; ready-made
header dicts for them are built once here. Two distinct comptrollers are
provided because the PRD forbids one operator from both submitting and
certifying, and from both issuing and settling.

The `Investor` role is entity-backed: "When `X-User-Role` is `Investor`,
`X-User-ID` is the `id` of the acting `Investor` row." Investor headers can
therefore only be built once an investor row exists, which is what
`make_investor_headers()` is for.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers.
GM_USER_ID = "u-gm-1"
GM_SECOND_USER_ID = "u-gm-2"
COMPTROLLER_USER_ID = "u-ct-1"
COMPTROLLER_SECOND_USER_ID = "u-ct-2"
COUNSEL_USER_ID = "u-sc-1"
PRODUCER_USER_ID = "u-lp-1"
PRODUCER_SECOND_USER_ID = "u-lp-2"

GM_HEADERS = build_user_headers(GM_USER_ID, Role.GENERAL_MANAGER)
GM2_HEADERS = build_user_headers(GM_SECOND_USER_ID, Role.GENERAL_MANAGER)
COMPTROLLER_HEADERS = build_user_headers(COMPTROLLER_USER_ID, Role.COMPTROLLER)
COMPTROLLER2_HEADERS = build_user_headers(
    COMPTROLLER_SECOND_USER_ID, Role.COMPTROLLER
)
COUNSEL_HEADERS = build_user_headers(COUNSEL_USER_ID, Role.SYNDICATION_COUNSEL)
PRODUCER_HEADERS = build_user_headers(PRODUCER_USER_ID, Role.LEAD_PRODUCER)
PRODUCER2_HEADERS = build_user_headers(PRODUCER_SECOND_USER_ID, Role.LEAD_PRODUCER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.GENERAL_MANAGER: GM_HEADERS,
    Role.COMPTROLLER: COMPTROLLER_HEADERS,
    Role.SYNDICATION_COUNSEL: COUNSEL_HEADERS,
    Role.LEAD_PRODUCER: PRODUCER_HEADERS,
}


def make_investor_headers(investor_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Investor role, keyed on the investor row id."""
    return build_user_headers(investor_id, Role.INVESTOR)


def headers_without_role(user_id: str = GM_USER_ID) -> Dict[str, str]:
    """Headers carrying only X-User-ID, for the missing-header rejection."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = Role.GENERAL_MANAGER) -> Dict[str, str]:
    """Headers carrying only X-User-Role, for the missing-header rejection."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = GM_USER_ID) -> Dict[str, str]:
    """Headers whose X-User-Role does not spell one of the five declared roles."""
    return build_user_headers(user_id, "GeneralManagerAssistant")
