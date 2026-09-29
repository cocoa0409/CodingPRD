"""Identity header builders for the seven roles.

``X-User-ID`` identifies the acting user and ``X-User-Role`` declares the
capacity in which that user acts.  Two roles carry opaque program identities;
the other five must present the identifier of a real row: a ``FacilityAdmin``
presents the ``Facility.id`` it acts for, and a ``FacilityScreener``,
``Audiologist``, ``Navigator`` or ``EICoordinator`` presents the ``Provider.id``
whose ``provider_type`` matches the role.
"""

from typing import Dict, Optional

from .constants import (
    ROLE_AUDIOLOGIST,
    ROLE_EI_COORDINATOR,
    ROLE_FACILITY_ADMIN,
    ROLE_FACILITY_SCREENER,
    ROLE_NAVIGATOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_PROGRAM_AUDITOR,
)
from .types import Headers

# Opaque program identities.  Nothing resolves them against a stored row, so
# any stable string works; distinct values matter only where the contract
# compares two operators to each other.
PROGRAM_ADMIN_ID = "admin-1"
PROGRAM_AUDITOR_ID = "auditor-1"
OPERATOR_ONE_ID = "op-1"
OPERATOR_TWO_ID = "op-2"
OPERATOR_NINE_ID = "op-9"

# Shared registry of the identities the suite uses.  ``user_id`` is None for
# every entity-backed role because the value is only known once the backing
# row has been created.
TEST_USERS: Dict[str, Dict[str, Optional[str]]] = {
    "program_admin": {"role": ROLE_PROGRAM_ADMIN, "user_id": PROGRAM_ADMIN_ID},
    "program_auditor": {"role": ROLE_PROGRAM_AUDITOR, "user_id": PROGRAM_AUDITOR_ID},
    "operator_one": {"role": ROLE_PROGRAM_AUDITOR, "user_id": OPERATOR_ONE_ID},
    "operator_two": {"role": ROLE_PROGRAM_AUDITOR, "user_id": OPERATOR_TWO_ID},
    "facility_admin": {"role": ROLE_FACILITY_ADMIN, "user_id": None},
    "facility_screener": {"role": ROLE_FACILITY_SCREENER, "user_id": None},
    "audiologist": {"role": ROLE_AUDIOLOGIST, "user_id": None},
    "navigator": {"role": ROLE_NAVIGATOR, "user_id": None},
    "ei_coordinator": {"role": ROLE_EI_COORDINATOR, "user_id": None},
}


def make_headers(user_id: str, role: str) -> Headers:
    """Build the two identity headers for an arbitrary user/role pair."""
    return {"X-User-ID": str(user_id), "X-User-Role": role}


# --- opaque program identities ----------------------------------------------


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> Headers:
    return make_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_program_auditor_headers(user_id: str = PROGRAM_AUDITOR_ID) -> Headers:
    return make_headers(user_id, ROLE_PROGRAM_AUDITOR)


# --- entity-backed identities ------------------------------------------------


def make_facility_admin_headers(user_id: str) -> Headers:
    """``user_id`` must be the ``Facility.id`` the request acts for."""
    return make_headers(user_id, ROLE_FACILITY_ADMIN)


def make_facility_screener_headers(user_id: str) -> Headers:
    """``user_id`` must be a ``Provider.id`` whose type is ``SCREENER``."""
    return make_headers(user_id, ROLE_FACILITY_SCREENER)


def make_audiologist_headers(user_id: str) -> Headers:
    """``user_id`` must be a ``Provider.id`` whose type is ``AUDIOLOGIST``."""
    return make_headers(user_id, ROLE_AUDIOLOGIST)


def make_navigator_headers(user_id: str) -> Headers:
    """``user_id`` must be a ``Provider.id`` whose type is ``NAVIGATOR``."""
    return make_headers(user_id, ROLE_NAVIGATOR)


def make_ei_coordinator_headers(user_id: str) -> Headers:
    """``user_id`` must be a ``Provider.id`` whose type is ``EI_COORDINATOR``."""
    return make_headers(user_id, ROLE_EI_COORDINATOR)


HEADER_BUILDERS = {
    ROLE_PROGRAM_ADMIN: make_program_admin_headers,
    ROLE_PROGRAM_AUDITOR: make_program_auditor_headers,
    ROLE_FACILITY_ADMIN: make_facility_admin_headers,
    ROLE_FACILITY_SCREENER: make_facility_screener_headers,
    ROLE_AUDIOLOGIST: make_audiologist_headers,
    ROLE_NAVIGATOR: make_navigator_headers,
    ROLE_EI_COORDINATOR: make_ei_coordinator_headers,
}
