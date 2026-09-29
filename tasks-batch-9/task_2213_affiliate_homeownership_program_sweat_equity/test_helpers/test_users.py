"""Acting identities for every role.

The PRD splits the seven roles in two. Five roles have opaque identities: their
``X-User-ID`` is "an opaque operator identifier not tied to any persisted
entity", so a fixed literal per operator is exactly right, and distinct
literals are what make the segregation-of-duties checks observable.

Two roles are entity-backed: an ``Applicant``'s ``X-User-ID`` is the id of the
acting household and a ``Volunteer``'s is the id of the acting volunteer
profile. Those headers can only be built once the owning row exists, so they
are produced by the two factory functions below from a server-minted id -- never
from a shared constant, because a shared id across distinct owners would make
the ownership checks untestable.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPLICANT,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_FAMILY_SERVICES_COORDINATOR,
    ROLE_MORTGAGE_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_SELECTION_COMMITTEE_MEMBER,
    ROLE_VOLUNTEER,
)

# --- Opaque operator identities -------------------------------------------
ADMIN_USER_ID = "admin-1"
COORDINATOR_USER_ID = "fsc-1"
#: The officer who structures a loan. Never approves or denies it.
OFFICER_USER_ID = "officer-1"
#: The officer who approves or denies. Never the one who submitted underwriting.
APPROVER_USER_ID = "officer-2"
CREW_LEAD_USER_ID = "cm-1"
COMMITTEE_ALICE_USER_ID = "committee-alice"
COMMITTEE_BRUNO_USER_ID = "committee-bruno"

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
COORDINATOR = build_user_headers(COORDINATOR_USER_ID, ROLE_FAMILY_SERVICES_COORDINATOR)
OFFICER = build_user_headers(OFFICER_USER_ID, ROLE_MORTGAGE_OFFICER)
APPROVER = build_user_headers(APPROVER_USER_ID, ROLE_MORTGAGE_OFFICER)
CREW_LEAD = build_user_headers(CREW_LEAD_USER_ID, ROLE_CONSTRUCTION_MANAGER)
COMMITTEE_ALICE = build_user_headers(COMMITTEE_ALICE_USER_ID, ROLE_SELECTION_COMMITTEE_MEMBER)
COMMITTEE_BRUNO = build_user_headers(COMMITTEE_BRUNO_USER_ID, ROLE_SELECTION_COMMITTEE_MEMBER)

#: The five opaque roles keyed by role name, for cross-role permission sweeps.
OPAQUE_HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: ADMIN,
    ROLE_FAMILY_SERVICES_COORDINATOR: COORDINATOR,
    ROLE_MORTGAGE_OFFICER: OFFICER,
    ROLE_CONSTRUCTION_MANAGER: CREW_LEAD,
    ROLE_SELECTION_COMMITTEE_MEMBER: COMMITTEE_ALICE,
}


# --- Entity-backed identities ---------------------------------------------
def make_applicant_headers(household_id: str) -> Dict[str, str]:
    """Headers for a partner family acting on its own file."""
    return build_user_headers(household_id, ROLE_APPLICANT)


def make_volunteer_headers(volunteer_id: str) -> Dict[str, str]:
    """Headers for a community volunteer acting on its own seat."""
    return build_user_headers(volunteer_id, ROLE_VOLUNTEER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for the authentication-ladder probes."""
    return build_user_headers(user_id, role)


#: Sent when a test needs a request with neither authentication header.
NO_HEADERS: Optional[Dict[str, str]] = None
