"""Role headers for the six studio roles of PRD §2.1.

For the five internal roles the ``X-User-ID`` value is an opaque operator
identifier that is never compared against any entity primary key.  For a
``PartnerRepresentative`` the identifier must be the ``id`` of the acting
``OutsourcePartner`` row, so those headers are always built per partner with
:func:`make_partner_representative_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_PRODUCTION_MANAGER = "ProductionManager"
ROLE_ARTIST = "Artist"
ROLE_SUPERVISOR = "Supervisor"
ROLE_DIRECTOR = "Director"
ROLE_OUTSOURCE_COORDINATOR = "OutsourceCoordinator"
ROLE_PARTNER_REPRESENTATIVE = "PartnerRepresentative"

# Opaque operator identifiers used across the suite.
PM_USER_ID = "u-pm-01"
PM_USER_ID_ALT = "u-pm-02"
ARTIST_USER_ID = "u-artist-01"
ARTIST_USER_ID_ALT = "u-artist-02"
SUPERVISOR_USER_ID = "u-sup-01"
SUPERVISOR_USER_ID_ALT = "u-sup-02"
DIRECTOR_USER_ID = "u-dir-01"
DIRECTOR_USER_ID_ALT = "u-dir-02"
COORDINATOR_USER_ID = "u-oc-01"
COORDINATOR_USER_ID_ALT = "u-oc-02"

PRODUCTION_MANAGER_HEADERS = build_user_headers(PM_USER_ID, ROLE_PRODUCTION_MANAGER)
PRODUCTION_MANAGER_ALT_HEADERS = build_user_headers(PM_USER_ID_ALT, ROLE_PRODUCTION_MANAGER)
ARTIST_HEADERS = build_user_headers(ARTIST_USER_ID, ROLE_ARTIST)
ARTIST_ALT_HEADERS = build_user_headers(ARTIST_USER_ID_ALT, ROLE_ARTIST)
SUPERVISOR_HEADERS = build_user_headers(SUPERVISOR_USER_ID, ROLE_SUPERVISOR)
SUPERVISOR_ALT_HEADERS = build_user_headers(SUPERVISOR_USER_ID_ALT, ROLE_SUPERVISOR)
DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_DIRECTOR)
DIRECTOR_ALT_HEADERS = build_user_headers(DIRECTOR_USER_ID_ALT, ROLE_DIRECTOR)
COORDINATOR_HEADERS = build_user_headers(COORDINATOR_USER_ID, ROLE_OUTSOURCE_COORDINATOR)
COORDINATOR_ALT_HEADERS = build_user_headers(COORDINATOR_USER_ID_ALT, ROLE_OUTSOURCE_COORDINATOR)


def make_artist_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary artist operator identifier."""
    return build_user_headers(user_id, ROLE_ARTIST)


def make_supervisor_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary supervisor operator identifier."""
    return build_user_headers(user_id, ROLE_SUPERVISOR)


def make_director_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary director operator identifier."""
    return build_user_headers(user_id, ROLE_DIRECTOR)


def make_production_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary production manager operator identifier."""
    return build_user_headers(user_id, ROLE_PRODUCTION_MANAGER)


def make_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary outsourcing coordinator operator identifier."""
    return build_user_headers(user_id, ROLE_OUTSOURCE_COORDINATOR)


def make_partner_representative_headers(partner_id: str) -> Dict[str, str]:
    """Headers for the vendor role, whose ``X-User-ID`` is the partner's ``id``."""
    return build_user_headers(partner_id, ROLE_PARTNER_REPRESENTATIVE)
