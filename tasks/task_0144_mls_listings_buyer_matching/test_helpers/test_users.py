"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- ListingAgent is ENTITY-BACKED. "When X-User-Role is ListingAgent,
  X-User-ID is the id of the acting Agent record, and ownership checks
  on any listing-side action compare the Listing's listing_agent_id to
  X-User-ID."
- BuyerAgent is ENTITY-BACKED. "When X-User-Role is BuyerAgent,
  X-User-ID is likewise the id of the acting Agent, and ownership
  checks on any buyer-side action compare the Buyer's buyer_agent_id
  to X-User-ID."
- MlsAdmin is OPAQUE. "X-User-ID is an opaque operator identifier that
  is not tied to any persisted entity. The server may accept any
  non-empty value as long as the role permits the requested operation;
  no comparison to an Agent.id is performed."

Every ListingAgent- or BuyerAgent-acting call whose success depends on
owning the targeted resource MUST mint headers via
make_listing_agent_headers(agent["id"]) / make_buyer_agent_headers(agent["id"])
— never via the shared LISTING_AGENT_FALLBACK_ID / BUYER_AGENT_FALLBACK_ID
constants. Falling back to a shared constant reproduces the canonical
bug: the literal "fallback-listing-agent-1" never equals any real
Agent.id, so every ownership check rejects every request as
ERR_FORBIDDEN_NOT_OWNER, cascading "Setup failed" into dozens of tests.

The shared-constant entries are SAFE only for:
- ERR_AUTH_MISSING / ERR_AUTH_INVALID negative tests where the header
  is intentionally malformed.
- ERR_NOT_FOUND tests where the targeted resource does not exist.
- ERR_FORBIDDEN tests that exercise role-permission (not ownership).
- Calls by MlsAdmin (opaque role; shared constant is canonical).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifier — PRD §2.1.
# ---------------------------------------------------------------------------
MLS_ADMIN_ID = "mls-admin-001"
MLS_ADMIN_ID_ALT = "mls-admin-002"


# ---------------------------------------------------------------------------
# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# Safe only for header-missing / role-mismatch / 404-on-non-existent /
# 403-on-other-agent paths.
# ---------------------------------------------------------------------------
LISTING_AGENT_FALLBACK_ID = "fallback-listing-agent-1"
BUYER_AGENT_FALLBACK_ID = "fallback-buyer-agent-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque MlsAdmin — shared constant is canonical.
    "mls_admin_headers": build_user_headers(MLS_ADMIN_ID, "MlsAdmin"),
    "mls_admin_headers_alt": build_user_headers(
        MLS_ADMIN_ID_ALT, "MlsAdmin",
    ),
    # Entity-backed ListingAgent fallback — DO NOT use for
    # ownership-gated calls.
    "listing_agent_fallback_headers": build_user_headers(
        LISTING_AGENT_FALLBACK_ID, "ListingAgent",
    ),
    # Entity-backed BuyerAgent fallback — DO NOT use for ownership-gated
    # calls.
    "buyer_agent_fallback_headers": build_user_headers(
        BUYER_AGENT_FALLBACK_ID, "BuyerAgent",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_listing_agent_headers(agent_id: str) -> Dict[str, str]:
    """For ListingAgent (entity_backed:Agent). Pass the actual Agent.id
    of the acting listing-side agent.

    PRD §2.1: "When X-User-Role is ListingAgent, X-User-ID is the id of
    the acting Agent record, and ownership checks on any listing-side
    action compare the Listing's listing_agent_id to X-User-ID."

    Every listing-side call whose success depends on owning the
    targeted Listing MUST use this builder, not the shared
    LISTING_AGENT_FALLBACK_ID constant.
    """
    return build_user_headers(agent_id, "ListingAgent")


def make_buyer_agent_headers(agent_id: str) -> Dict[str, str]:
    """For BuyerAgent (entity_backed:Agent). Pass the actual Agent.id
    of the acting buyer-side agent.

    PRD §2.1: "When X-User-Role is BuyerAgent, X-User-ID is likewise
    the id of the acting Agent, and ownership checks on any buyer-side
    action compare the Buyer's buyer_agent_id to X-User-ID."

    Every buyer-side call whose success depends on owning the targeted
    Buyer MUST use this builder, not the shared BUYER_AGENT_FALLBACK_ID
    constant.
    """
    return build_user_headers(agent_id, "BuyerAgent")


def make_mls_admin_headers(admin_id: str) -> Dict[str, str]:
    """For MlsAdmin (opaque). Any non-empty operator id is fine; this
    builder exists for tests that want a distinct admin id."""
    return build_user_headers(admin_id, "MlsAdmin")


__all__ = [
    "MLS_ADMIN_ID",
    "MLS_ADMIN_ID_ALT",
    "LISTING_AGENT_FALLBACK_ID",
    "BUYER_AGENT_FALLBACK_ID",
    "TEST_USERS",
    "make_listing_agent_headers",
    "make_buyer_agent_headers",
    "make_mls_admin_headers",
]
