"""Header sets for the seven roles of PRD §2.1.

The five operator roles carry opaque identities, so a fixed identifier is fine
for them. The two entity-backed roles must not use a fixed identifier: PRD §2.1
says ``X-User-ID`` *is* the acting ``BrokerDealer.id`` or ``Investor.id``, so
tests build those headers from a real row's id via the ``make_*`` helpers.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque operator identities (PRD §2.1) ────────────────────────────

SPONSOR_OPERATOR_ID = "op-sponsor-001"
COMPLIANCE_OFFICER_ID = "op-compliance-001"
ADVISOR_ID = "op-advisor-001"
TRANSFER_AGENT_ID = "op-transfer-agent-001"
BOARD_COMMITTEE_ID = "op-board-001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "sponsor_operator": build_user_headers(SPONSOR_OPERATOR_ID, UserRole.SPONSOR_OPERATOR),
    "compliance_officer": build_user_headers(
        COMPLIANCE_OFFICER_ID, UserRole.COMPLIANCE_OFFICER
    ),
    "advisor": build_user_headers(ADVISOR_ID, UserRole.INDEPENDENT_VALUATION_ADVISOR),
    "transfer_agent": build_user_headers(TRANSFER_AGENT_ID, UserRole.TRANSFER_AGENT),
    "board_committee": build_user_headers(BOARD_COMMITTEE_ID, UserRole.BOARD_COMMITTEE),
}

SPONSOR = TEST_USERS["sponsor_operator"]
COMPLIANCE = TEST_USERS["compliance_officer"]
ADVISOR = TEST_USERS["advisor"]
TRANSFER_AGENT = TEST_USERS["transfer_agent"]
BOARD = TEST_USERS["board_committee"]


# ─── Entity-backed identities (PRD §2.1) ──────────────────────────────

def make_broker_dealer_rep_headers(broker_dealer_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``BrokerDealer``."""
    return build_user_headers(broker_dealer_id, UserRole.BROKER_DEALER_REP)


def make_investor_user_headers(investor_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Investor``."""
    return build_user_headers(investor_id, UserRole.INVESTOR_USER)


def headers_for_role(role: str, user_id: str = "op-generic-001") -> Dict[str, str]:
    """Headers for an arbitrary role name — used by role-matrix tests."""
    return build_user_headers(user_id, role)


# ─── Malformed identities (PRD §2.1 authentication rules) ─────────────

NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_ROLE_HEADER: Dict[str, str] = {
    "X-User-ID": SPONSOR_OPERATOR_ID,
    "Content-Type": "application/json",
}

MISSING_USER_ID_HEADER: Dict[str, str] = {
    "X-User-Role": UserRole.SPONSOR_OPERATOR,
    "Content-Type": "application/json",
}

BLANK_ROLE_HEADER: Dict[str, str] = build_user_headers(SPONSOR_OPERATOR_ID, "")

UNKNOWN_ROLE_HEADER: Dict[str, str] = build_user_headers(
    SPONSOR_OPERATOR_ID, "PortfolioManager"
)
