"""Request-header builders for each role, plus deliberately malformed ones.

Every endpoint requires both ``X-User-ID`` and ``X-User-Role``. For
``TalentBuyer``, ``TourAccountant`` and ``RiskOfficer`` the user id is opaque.
For ``ArtistRep`` the user id must be the acting ``Artist.id`` and for
``VenueOperator`` it must be the acting ``Venue.id``.
"""

import uuid
from typing import Dict, Optional

from .constants import (
    ROLE_ARTIST_REP,
    ROLE_RISK_OFFICER,
    ROLE_TALENT_BUYER,
    ROLE_TOUR_ACCOUNTANT,
    ROLE_VENUE_OPERATOR,
)


def new_user_id() -> str:
    """Mint a fresh opaque actor identifier."""
    return str(uuid.uuid4())


def _headers(role: Optional[str], user_id: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


# ---------------------------------------------------------------------------
# Opaque-identity roles
# ---------------------------------------------------------------------------


def make_talent_buyer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(ROLE_TALENT_BUYER, user_id or new_user_id())


def make_tour_accountant_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(ROLE_TOUR_ACCOUNTANT, user_id or new_user_id())


def make_risk_officer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(ROLE_RISK_OFFICER, user_id or new_user_id())


# ---------------------------------------------------------------------------
# Entity-backed roles: identity must be threaded from the resource
# ---------------------------------------------------------------------------


def make_artist_rep_headers(artist_id: str) -> Dict[str, str]:
    """An ArtistRep acting for ``artist_id``; the id must equal show.artist_id."""
    return _headers(ROLE_ARTIST_REP, artist_id)


def make_venue_operator_headers(venue_id: str) -> Dict[str, str]:
    """A VenueOperator acting for ``venue_id``; the id must equal show.venue_id."""
    return _headers(ROLE_VENUE_OPERATOR, venue_id)


def make_headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role string, minting an opaque id when needed."""
    return _headers(role, user_id or new_user_id())


# ---------------------------------------------------------------------------
# Deliberately malformed identities
# ---------------------------------------------------------------------------


def make_headers_without_user_id(role: str = ROLE_TALENT_BUYER) -> Dict[str, str]:
    return _headers(role, None)


def make_headers_with_empty_user_id(role: str = ROLE_TALENT_BUYER) -> Dict[str, str]:
    return _headers(role, "")


def make_headers_without_role(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers(None, user_id or new_user_id())


def make_headers_with_empty_role(user_id: Optional[str] = None) -> Dict[str, str]:
    return _headers("", user_id or new_user_id())


def make_headers_with_no_identity() -> Dict[str, str]:
    return _headers(None, None)


def make_unknown_role_headers(
    role: str = "ShowRunner", user_id: Optional[str] = None
) -> Dict[str, str]:
    """Headers carrying a role string the service does not define."""
    return _headers(role, user_id or new_user_id())
