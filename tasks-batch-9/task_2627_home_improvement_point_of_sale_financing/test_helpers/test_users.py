"""Auth headers for the six program roles.

The four opaque roles carry operator handles that are never compared to any
entity id, so a module-level constant per operator is safe and readable.

The two entity-backed roles are different: ``X-User-ID`` must be the row id of
the acting ``Merchant`` or ``Consumer``, so those headers can only be built once
the row exists.  Use :func:`merchant_headers` and :func:`consumer_headers` —
never a shared constant — for anything ownership-gated.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CONSUMER,
    ROLE_MERCHANT,
    ROLE_PROGRAM_ADMIN,
    ROLE_PROGRAM_UNDERWRITER,
    ROLE_RISK_ANALYST,
    ROLE_SERVICING_AGENT,
)

# ─── Opaque operator handles ──────────────────────────

PROGRAM_ADMIN_ID = "pa-1"
UNDERWRITER_ID = "uw-1"
SECOND_UNDERWRITER_ID = "uw-2"
RISK_ANALYST_ID = "ra-1"
SECOND_RISK_ANALYST_ID = "ra-2"
SERVICING_AGENT_ID = "sa-1"
SECOND_SERVICING_AGENT_ID = "sa-2"

ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)
UNDERWRITER_HEADERS = build_user_headers(UNDERWRITER_ID, ROLE_PROGRAM_UNDERWRITER)
SECOND_UNDERWRITER_HEADERS = build_user_headers(
    SECOND_UNDERWRITER_ID, ROLE_PROGRAM_UNDERWRITER
)
ANALYST_HEADERS = build_user_headers(RISK_ANALYST_ID, ROLE_RISK_ANALYST)
SECOND_ANALYST_HEADERS = build_user_headers(SECOND_RISK_ANALYST_ID, ROLE_RISK_ANALYST)
AGENT_HEADERS = build_user_headers(SERVICING_AGENT_ID, ROLE_SERVICING_AGENT)
SECOND_AGENT_HEADERS = build_user_headers(
    SECOND_SERVICING_AGENT_ID, ROLE_SERVICING_AGENT
)

#: Role name -> headers, for the four roles whose identity is opaque.
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: ADMIN_HEADERS,
    ROLE_PROGRAM_UNDERWRITER: UNDERWRITER_HEADERS,
    ROLE_RISK_ANALYST: ANALYST_HEADERS,
    ROLE_SERVICING_AGENT: AGENT_HEADERS,
}


# ─── Entity-backed identity builders ──────────────────

def merchant_headers(merchant_id: str) -> Dict[str, str]:
    """Headers for a `Merchant` acting as itself; `X-User-ID` is the merchant row id."""
    return build_user_headers(merchant_id, ROLE_MERCHANT)


def consumer_headers(consumer_id: str) -> Dict[str, str]:
    """Headers for a `Consumer` acting as itself; `X-User-ID` is the consumer row id."""
    return build_user_headers(consumer_id, ROLE_CONSUMER)


def headers_for(role: str, entity_id: str = "") -> Dict[str, str]:
    """Headers for any role: entity-backed roles need `entity_id`, opaque roles ignore it."""
    if role == ROLE_MERCHANT:
        return merchant_headers(entity_id)
    if role == ROLE_CONSUMER:
        return consumer_headers(entity_id)
    return dict(TEST_USERS[role])


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying `X-User-ID` but no `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying `X-User-Role` but no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
