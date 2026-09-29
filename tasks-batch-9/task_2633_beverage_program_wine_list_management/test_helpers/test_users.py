"""Per-role header builders.

Two of the five roles declared in the PRD are entity-backed: a
``VenueSommelier``'s X-User-ID must be the id of the Venue it acts for, and a
``DistributorRep``'s X-User-ID must be the id of its Distributor.  Those two
therefore have no module-level constant header dict -- callers must build the
headers per test from the id the setup actually created.

The three opaque roles (``BeverageDirector``, ``Controller``,
``ComplianceOfficer``) are not scoped to any entity, so a stable uuid per role
is sufficient.
"""
import uuid

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque roles: stable synthetic actor ids ---------------------------
BEVERAGE_DIRECTOR_ID = "11111111-1111-4111-8111-111111111111"
CONTROLLER_ID = "22222222-2222-4222-8222-222222222222"
COMPLIANCE_OFFICER_ID = "33333333-3333-4333-8333-333333333333"

BEVERAGE_DIRECTOR_HEADERS = build_user_headers(
    BEVERAGE_DIRECTOR_ID, UserRole.BEVERAGE_DIRECTOR.value)
CONTROLLER_HEADERS = build_user_headers(
    CONTROLLER_ID, UserRole.CONTROLLER.value)
COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    COMPLIANCE_OFFICER_ID, UserRole.COMPLIANCE_OFFICER.value)


def director_headers(user_id=None):
    """Headers for a BeverageDirector; pass a distinct user_id when a test
    needs a second director to satisfy segregation of duties."""
    return build_user_headers(user_id or BEVERAGE_DIRECTOR_ID,
                              UserRole.BEVERAGE_DIRECTOR.value)


def second_director_headers():
    """A BeverageDirector distinct from ``BEVERAGE_DIRECTOR_HEADERS``."""
    return build_user_headers("11111111-1111-4111-8111-1111111111a2",
                              UserRole.BEVERAGE_DIRECTOR.value)


def controller_headers(user_id=None):
    return build_user_headers(user_id or CONTROLLER_ID,
                              UserRole.CONTROLLER.value)


def second_controller_headers():
    """A Controller distinct from ``CONTROLLER_HEADERS``."""
    return build_user_headers("22222222-2222-4222-8222-2222222222a2",
                              UserRole.CONTROLLER.value)


def compliance_officer_headers(user_id=None):
    return build_user_headers(user_id or COMPLIANCE_OFFICER_ID,
                              UserRole.COMPLIANCE_OFFICER.value)


def sommelier_headers(venue_id):
    """Headers for the VenueSommelier of ``venue_id`` (entity-backed role)."""
    return build_user_headers(str(venue_id), UserRole.VENUE_SOMMELIER.value)


def distributor_rep_headers(distributor_id):
    """Headers for the DistributorRep of ``distributor_id`` (entity-backed)."""
    return build_user_headers(str(distributor_id), UserRole.DISTRIBUTOR_REP.value)


def headers_with_random_id(role):
    """Headers carrying a syntactically valid but unknown actor id."""
    return build_user_headers(str(uuid.uuid4()), role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": BEVERAGE_DIRECTOR_ID,
    "Content-Type": "application/json",
}
MISSING_ID_HEADERS = {
    "X-User-Role": UserRole.BEVERAGE_DIRECTOR.value,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers(BEVERAGE_DIRECTOR_ID, "WineBuyer")
