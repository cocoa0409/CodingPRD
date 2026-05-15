"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- CourtClerk, AuctionAdmin, Observer are OPAQUE: X-User-ID is an opaque
  operator identifier not tied to any persisted entity. The server may
  record it on AuditEvent.actor_id but does not compare it to any entity
  id. Shared constants are canonical for these roles.

- Bidder is ENTITY-BACKED: PRD §2.1 says "When X-User-Role is Bidder,
  X-User-ID is the id of the acting BidderAccount; ownership checks on
  any resource that references a BidderAccount — including Deposit,
  Bid, and Payment rows — compare the resource's bidder_account_id ...
  to X-User-ID." Therefore every ownership-gated Bidder call (POST /bids,
  POST /deposits/{id}/pay, POST /deposits/{id}/raise-dispute, POST
  /payments/{id}/settle, GET /bidder-accounts/{id}, GET /payments/{id})
  MUST mint its headers with the actual BidderAccount.id of the
  acting bidder via make_bidder_headers(account_id).

  The BIDDER_FALLBACK_ID shared constant below is ONLY safe for tests
  that DO NOT exercise ownership (header-missing, role-mismatch,
  NotFound paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers (PRD §2.1).
# ---------------------------------------------------------------------------
COURT_CLERK_ID = "clerk-001"
COURT_CLERK_ID_ALT = "clerk-002"

AUCTION_ADMIN_ID = "admin-001"
AUCTION_ADMIN_ID_ALT = "admin-002"

OBSERVER_ID = "observer-001"

# Fallback identifier for Bidder when ownership is NOT being tested
# (header-missing, role-mismatch, NotFound paths). DO NOT pass this
# into ownership-gated calls — use make_bidder_headers(account_id) with
# the real BidderAccount.id instead.
BIDDER_FALLBACK_ID = "fallback-bidder-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical.
    "court_clerk_headers": build_user_headers(COURT_CLERK_ID, "CourtClerk"),
    "court_clerk_headers_alt": build_user_headers(
        COURT_CLERK_ID_ALT, "CourtClerk",
    ),
    "auction_admin_headers": build_user_headers(
        AUCTION_ADMIN_ID, "AuctionAdmin",
    ),
    "auction_admin_headers_alt": build_user_headers(
        AUCTION_ADMIN_ID_ALT, "AuctionAdmin",
    ),
    "observer_headers": build_user_headers(OBSERVER_ID, "Observer"),
    # Entity-backed role — fallback constant ONLY for tests that don't
    # exercise ownership. Ownership-gated calls MUST use
    # make_bidder_headers(account["id"]).
    "bidder_headers": build_user_headers(BIDDER_FALLBACK_ID, "Bidder"),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for ownership-gated Bidder calls.
# PRD §2.1: "ownership checks on any resource that references a
# BidderAccount — including Deposit, Bid, and Payment rows — compare
# the resource's bidder_account_id ... to X-User-ID."
# ---------------------------------------------------------------------------
def make_bidder_headers(account_id: str) -> Dict[str, str]:
    """For Bidder (entity_backed:BidderAccount). Pass the
    BidderAccount.id of the acting bidder. Every Bidder call whose
    success depends on owning the targeted Deposit/Bid/Payment row MUST
    use this builder, not the BIDDER_FALLBACK_ID shared constant."""
    return build_user_headers(account_id, "Bidder")


# Opaque-role per-instance builders — useful when a test wants a
# distinct actor_id for audit-log distinguishability.
def make_court_clerk_headers(clerk_id: str) -> Dict[str, str]:
    return build_user_headers(clerk_id, "CourtClerk")


def make_auction_admin_headers(admin_id: str) -> Dict[str, str]:
    return build_user_headers(admin_id, "AuctionAdmin")


def make_observer_headers(observer_id: str) -> Dict[str, str]:
    return build_user_headers(observer_id, "Observer")


__all__ = [
    "COURT_CLERK_ID",
    "COURT_CLERK_ID_ALT",
    "AUCTION_ADMIN_ID",
    "AUCTION_ADMIN_ID_ALT",
    "OBSERVER_ID",
    "BIDDER_FALLBACK_ID",
    "TEST_USERS",
    "make_bidder_headers",
    "make_court_clerk_headers",
    "make_auction_admin_headers",
    "make_observer_headers",
]
