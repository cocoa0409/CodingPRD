"""Actor headers.

Identity is header-borne: every request carries an ``X-User-ID`` opaque
operator identifier and an ``X-User-Role``. Only the print vendor
representative role resolves its ``X-User-ID`` against a stored entity, so that
role's headers must always be built from a real print vendor id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BALLOT_COORDINATOR,
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_LANGUAGE_ACCESS_COORDINATOR,
    ROLE_PRINT_VENDOR_REP,
    ROLE_PUBLIC_OBSERVER,
    ROLE_VOTING_SYSTEM_TECHNICIAN,
    ROLE_WAREHOUSE_CUSTODIAN,
    USER_COORD,
    USER_COORD_2,
    USER_CUSTODIAN,
    USER_DIRECTOR,
    USER_DIRECTOR_2,
    USER_LANGUAGE,
    USER_OBSERVER,
    USER_TECH_1,
    USER_TECH_2,
    USER_TECH_3,
)


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Build the identity headers for an arbitrary operator id and role."""
    return build_user_headers(user_id, role)


# Canonical single-actor header bundles. Distinct operator ids are provided for
# the roles that carry a segregation-of-duties rule so a test can always find a
# second, different human holding the same role.

DIRECTOR = headers_for(USER_DIRECTOR, ROLE_ELECTIONS_DIRECTOR)
DIRECTOR_2 = headers_for(USER_DIRECTOR_2, ROLE_ELECTIONS_DIRECTOR)
COORDINATOR = headers_for(USER_COORD, ROLE_BALLOT_COORDINATOR)
COORDINATOR_2 = headers_for(USER_COORD_2, ROLE_BALLOT_COORDINATOR)
LANGUAGE_COORDINATOR = headers_for(USER_LANGUAGE, ROLE_LANGUAGE_ACCESS_COORDINATOR)
CUSTODIAN = headers_for(USER_CUSTODIAN, ROLE_WAREHOUSE_CUSTODIAN)
TECHNICIAN = headers_for(USER_TECH_1, ROLE_VOTING_SYSTEM_TECHNICIAN)
TECHNICIAN_2 = headers_for(USER_TECH_2, ROLE_VOTING_SYSTEM_TECHNICIAN)
TECHNICIAN_3 = headers_for(USER_TECH_3, ROLE_VOTING_SYSTEM_TECHNICIAN)
OBSERVER = headers_for(USER_OBSERVER, ROLE_PUBLIC_OBSERVER)


def vendor_rep(vendor_id: str) -> Dict[str, str]:
    """Headers for the representative of ``vendor_id``.

    The vendor representative's ``X-User-ID`` is the print vendor's own id, so
    a representative of one vendor cannot act for another vendor.
    """
    return headers_for(vendor_id, ROLE_PRINT_VENDOR_REP)


# Role name keyed lookup used by the role-matrix probes. Each entry pairs an
# operator id with the role under test; the vendor representative entry is
# deliberately absent because it needs a live vendor id.

ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    ROLE_ELECTIONS_DIRECTOR: DIRECTOR,
    ROLE_BALLOT_COORDINATOR: COORDINATOR,
    ROLE_LANGUAGE_ACCESS_COORDINATOR: LANGUAGE_COORDINATOR,
    ROLE_WAREHOUSE_CUSTODIAN: CUSTODIAN,
    ROLE_VOTING_SYSTEM_TECHNICIAN: TECHNICIAN,
    ROLE_PUBLIC_OBSERVER: OBSERVER,
}


def headers_without_role(user_id: str = USER_DIRECTOR) -> Dict[str, str]:
    """Headers carrying an operator id but no role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = USER_DIRECTOR,
                              role: str = "BallotArtist") -> Dict[str, str]:
    """Headers carrying a role string that is not one of the declared roles."""
    return headers_for(user_id, role)


def headers_without_user_id(role: str = ROLE_ELECTIONS_DIRECTOR) -> Dict[str, str]:
    """Headers carrying a role but no operator id."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
