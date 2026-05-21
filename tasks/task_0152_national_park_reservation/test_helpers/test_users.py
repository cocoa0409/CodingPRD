"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "The Visitor role is entity-backed: when X-User-Role is Visitor,
    the supplied X-User-ID is the id of the acting Visitor resource.
    Ownership checks on any resource that references a visitor (a
    campground reservation, a timed-entry reservation, a backcountry
    permit, a lottery application, a waitlist entry, an America the
    Beautiful Pass, a ledger entry) compare the resource's visitor_id
    to X-User-ID, and confirm/cancel/accept/decline actions on a
    resource owned by another visitor are rejected with ERR_FORBIDDEN.

    The remaining three roles — ParkAdmin, ParkRanger, and
    SystemOperator — are opaque operator identifiers not tied to any
    persisted entity."

The shared *_headers constants below use deterministic seed strings.
They are appropriate ONLY for:

    * Visitor-role tests whose success does NOT depend on the caller
      owning the subject resource (e.g., ERR_UNAUTHENTICATED probes,
      404-on-missing-visitor probes).
    * The three opaque roles (ParkAdmin, ParkRanger, SystemOperator),
      where X-User-ID is never compared against any entity id.

For any Visitor-scoped operation whose acceptance depends on the
caller being the resource owner (every confirm/cancel/accept/decline,
every wallet deposit, every ledger lookup, every reservation/permit
create call that records visitor_id), tests and fixtures MUST mint
headers via make_visitor_headers(visitor_id) with the real Visitor.id
returned by POST /visitors.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — safe for opaque roles and non-ownership Visitor tests.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Visitor — shared constant is reserved for non-ownership
    # tests (auth probes, 404 probes, RBAC probes that do not require the
    # caller's id to match a resource's visitor_id).
    "visitor_headers": build_user_headers("visitor-shared-0001", "Visitor"),
    # Opaque operator roles — X-User-ID is not compared to any entity.
    "park_admin_headers": build_user_headers(
        "park-admin-0001", "ParkAdmin",
    ),
    "park_ranger_headers": build_user_headers(
        "park-ranger-0001", "ParkRanger",
    ),
    "system_operator_headers": build_user_headers(
        "system-operator-0001", "SystemOperator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Visitor role
# whenever the downstream call is ownership-gated.
#
# PRD §2.1: "Ownership checks on any resource that references a visitor ...
# compare the resource's visitor_id to X-User-ID".
# ---------------------------------------------------------------------------
def make_visitor_headers(visitor_id: str) -> Dict[str, str]:
    """Headers for a specific Visitor. Use this whenever the call is
    ownership-gated — i.e. any operation that creates, reads, modifies,
    confirms, cancels, accepts, declines, or otherwise touches a
    resource that records visitor_id (TimedEntryReservation,
    CampgroundReservation, BackcountryPermit, LotteryApplication,
    WaitlistEntry, AmericaTheBeautifulPass, LedgerEntry, wallet deposits).
    """
    return build_user_headers(visitor_id, "Visitor")


def make_park_admin_headers(operator_id: str = "park-admin-0001") -> Dict[str, str]:
    """Headers for a ParkAdmin operator. PRD §2.1 declares this role
    opaque, so the operator_id is recorded for audit but not compared
    to any entity's id. The default deterministic id is sufficient
    for all ParkAdmin tests.
    """
    return build_user_headers(operator_id, "ParkAdmin")


def make_park_ranger_headers(operator_id: str = "park-ranger-0001") -> Dict[str, str]:
    """Headers for a ParkRanger operator. Opaque role per PRD §2.1."""
    return build_user_headers(operator_id, "ParkRanger")


def make_system_operator_headers(
    operator_id: str = "system-operator-0001",
) -> Dict[str, str]:
    """Headers for a SystemOperator. Opaque role per PRD §2.1."""
    return build_user_headers(operator_id, "SystemOperator")


__all__ = [
    "TEST_USERS",
    "make_visitor_headers",
    "make_park_admin_headers",
    "make_park_ranger_headers",
    "make_system_operator_headers",
]
