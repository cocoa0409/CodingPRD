"""Test identities and header builders for the seven roles.

Three roles are entity-backed: a ``VenueManager`` is identified by the id of the
venue it manages, a ``CompetitorTeam`` by its competitor id and a ``SponsorRep``
by its sponsor id. Calls made under those roles must therefore carry the id of
the specific row under test, which is why every builder accepts ``user_id``.

The four opaque roles use stable distinct ids so that segregation of duties can
be exercised: a safety plan may not be certified by its author, and a settlement
may not be approved by its preparer.
"""

from __future__ import annotations

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Shared identities keyed by role name. Entity-backed roles carry a placeholder
#: id that must be replaced with a real row id at call time.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "SeriesPromoter": {"user_id": "promoter-1", "role": Role.SERIES_PROMOTER.value},
    "VenueManager": {"user_id": "venue-manager-1", "role": Role.VENUE_MANAGER.value},
    "CompetitorTeam": {
        "user_id": "competitor-team-1",
        "role": Role.COMPETITOR_TEAM.value,
    },
    "SafetyOfficial": {
        "user_id": "so-author-1",
        "role": Role.SAFETY_OFFICIAL.value,
    },
    "TicketingManager": {
        "user_id": "ticketing-1",
        "role": Role.TICKETING_MANAGER.value,
    },
    "SponsorRep": {"user_id": "sponsor-rep-1", "role": Role.SPONSOR_REP.value},
    "FinanceController": {
        "user_id": "fc-preparer-1",
        "role": Role.FINANCE_CONTROLLER.value,
    },
}

# ---------------------------------------------------------------------------
# Stable opaque identities used for segregation of duties
# ---------------------------------------------------------------------------

#: Safety official who authors and submits plans.
SAFETY_AUTHOR_USER_ID: str = "so-author-1"

#: A different safety official, who may certify or return a submitted plan.
SAFETY_CERTIFIER_USER_ID: str = "so-certifier-2"

#: Safety official who files technical inspections.
SAFETY_INSPECTOR_USER_ID: str = "so-inspector-1"

#: Finance controller who prepares settlements.
FINANCE_PREPARER_USER_ID: str = "fc-preparer-1"

#: A different finance controller, who may approve a prepared settlement.
FINANCE_APPROVER_USER_ID: str = "fc-approver-2"

#: Series promoter identity.
PROMOTER_USER_ID: str = "promoter-1"

#: Ticketing manager identity.
TICKETING_USER_ID: str = "ticketing-1"


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_series_promoter_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``SeriesPromoter`` call."""
    return build_user_headers(user_id or PROMOTER_USER_ID, Role.SERIES_PROMOTER.value)


def make_venue_manager_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``VenueManager`` call.

    ``user_id`` must be the id of the venue the caller manages, because the role
    is entity-backed and ownership is checked against it.
    """
    return build_user_headers(
        user_id or TEST_USERS["VenueManager"]["user_id"], Role.VENUE_MANAGER.value
    )


def make_competitor_team_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``CompetitorTeam`` call.

    ``user_id`` must be the id of the competitor the caller races for.
    """
    return build_user_headers(
        user_id or TEST_USERS["CompetitorTeam"]["user_id"], Role.COMPETITOR_TEAM.value
    )


def make_safety_official_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``SafetyOfficial`` call. Defaults to the plan author."""
    return build_user_headers(
        user_id or SAFETY_AUTHOR_USER_ID, Role.SAFETY_OFFICIAL.value
    )


def make_ticketing_manager_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``TicketingManager`` call."""
    return build_user_headers(user_id or TICKETING_USER_ID, Role.TICKETING_MANAGER.value)


def make_sponsor_rep_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``SponsorRep`` call.

    ``user_id`` must be the id of the sponsor the caller represents.
    """
    return build_user_headers(
        user_id or TEST_USERS["SponsorRep"]["user_id"], Role.SPONSOR_REP.value
    )


def make_finance_controller_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a ``FinanceController`` call. Defaults to the preparer."""
    return build_user_headers(
        user_id or FINANCE_PREPARER_USER_ID, Role.FINANCE_CONTROLLER.value
    )


# Convenience aliases for the two segregated pairs -------------------------


def make_safety_author_headers() -> Dict[str, str]:
    """Headers for the safety official who authors and submits plans."""
    return make_safety_official_headers(SAFETY_AUTHOR_USER_ID)


def make_safety_certifier_headers() -> Dict[str, str]:
    """Headers for the second safety official, who certifies or returns."""
    return make_safety_official_headers(SAFETY_CERTIFIER_USER_ID)


def make_safety_inspector_headers() -> Dict[str, str]:
    """Headers for the safety official who files technical inspections."""
    return make_safety_official_headers(SAFETY_INSPECTOR_USER_ID)


def make_finance_preparer_headers() -> Dict[str, str]:
    """Headers for the finance controller who prepares settlements."""
    return make_finance_controller_headers(FINANCE_PREPARER_USER_ID)


def make_finance_approver_headers() -> Dict[str, str]:
    """Headers for the second finance controller, who approves settlements."""
    return make_finance_controller_headers(FINANCE_APPROVER_USER_ID)


def make_headers(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role name, with an optional explicit identity."""
    if role not in TEST_USERS:
        raise ValueError(f"Unknown role: {role}")
    return build_user_headers(user_id or TEST_USERS[role]["user_id"], role)


def make_headers_without_identity() -> Dict[str, str]:
    """Headers carrying no identity at all, for unauthenticated calls."""
    return {"Content-Type": "application/json"}
