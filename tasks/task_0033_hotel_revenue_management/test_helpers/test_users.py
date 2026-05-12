"""Pre-built role headers for every role in the PRD.

PRD §2.1 (verbatim): 'For every role, X-User-ID is treated as an opaque
operator identifier that the server does not resolve against any persisted
entity table — there is no user-account collection in this domain.'

Therefore every role here is opaque — the shared TEST_USERS constants are
canonical (no entity_backed identity threading required). The exception
is the segregation-of-duties workflow on RateOverride approve/reject:
the server records the submitting analyst's X-User-ID and rejects an
approver request whose X-User-ID matches that recorded value
(ERR_SEGREGATION_OF_DUTIES, PRD §3.3 / §2.9).

To exercise the segregation rule, tests need at least two distinct
X-User-IDs per role; the per-role builders below produce them.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared canonical opaque-role headers
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin
    "admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "admin_headers_alt": build_user_headers("admin-002", "PlatformAdmin"),

    # RevenueAnalyst (submitter side of approval chain)
    "analyst_headers": build_user_headers("analyst-001", "RevenueAnalyst"),
    "analyst_headers_alt": build_user_headers("analyst-002", "RevenueAnalyst"),

    # RevenueManager (approver side of approval chain)
    "manager_headers": build_user_headers("manager-001", "RevenueManager"),
    "manager_headers_alt": build_user_headers("manager-002", "RevenueManager"),

    # ReservationsAgent
    "agent_headers": build_user_headers("agent-001", "ReservationsAgent"),
    "agent_headers_alt": build_user_headers("agent-002", "ReservationsAgent"),

    # FrontDeskClerk
    "clerk_headers": build_user_headers("clerk-001", "FrontDeskClerk"),
    "clerk_headers_alt": build_user_headers("clerk-002", "FrontDeskClerk"),

    # HousekeepingStaff
    "housekeeping_headers": build_user_headers("housekeeper-001",
                                               "HousekeepingStaff"),
    "housekeeping_headers_alt": build_user_headers("housekeeper-002",
                                                   "HousekeepingStaff"),

    # Guest
    "guest_headers": build_user_headers("guest-001", "Guest"),
    "guest_headers_alt": build_user_headers("guest-002", "Guest"),
}


# ---------------------------------------------------------------------------
# Per-instance builders. PRD §2.1: identity is opaque for every role,
# so passing a custom user_id is purely for observable distinction
# (segregation-of-duties checks; AuditLog.actor_id assertions).
# ---------------------------------------------------------------------------
def make_admin_headers(user_id: str = "admin-001") -> Dict[str, str]:
    """PlatformAdmin headers; identity is opaque per PRD §2.1."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_analyst_headers(user_id: str = "analyst-001") -> Dict[str, str]:
    """RevenueAnalyst headers; identity is opaque per PRD §2.1.

    The server records the submitter's X-User-ID into the RateOverride
    workflow; pass distinct ids when exercising segregation of duties.
    """
    return build_user_headers(user_id, "RevenueAnalyst")


def make_manager_headers(user_id: str = "manager-001") -> Dict[str, str]:
    """RevenueManager headers; identity is opaque per PRD §2.1.

    On approve / reject of a RateOverride, the server compares this
    X-User-ID against the recorded submitter id and rejects on equality
    with ERR_SEGREGATION_OF_DUTIES.
    """
    return build_user_headers(user_id, "RevenueManager")


def make_agent_headers(user_id: str = "agent-001") -> Dict[str, str]:
    """ReservationsAgent headers; identity is opaque per PRD §2.1."""
    return build_user_headers(user_id, "ReservationsAgent")


def make_clerk_headers(user_id: str = "clerk-001") -> Dict[str, str]:
    """FrontDeskClerk headers; identity is opaque per PRD §2.1."""
    return build_user_headers(user_id, "FrontDeskClerk")


def make_housekeeping_headers(user_id: str = "housekeeper-001") -> Dict[str, str]:
    """HousekeepingStaff headers; identity is opaque per PRD §2.1."""
    return build_user_headers(user_id, "HousekeepingStaff")


def make_guest_headers(user_id: str = "guest-001") -> Dict[str, str]:
    """Guest headers; identity is opaque per PRD §2.1."""
    return build_user_headers(user_id, "Guest")


__all__ = [
    "TEST_USERS",
    "make_admin_headers",
    "make_analyst_headers",
    "make_manager_headers",
    "make_agent_headers",
    "make_clerk_headers",
    "make_housekeeping_headers",
    "make_guest_headers",
]
