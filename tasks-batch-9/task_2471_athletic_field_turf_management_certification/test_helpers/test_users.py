"""Identity threading for the five entity-backed roles.

Every role in this service is entity-backed: `X-User-ID` must be the `id` of a
real `StaffMember` row whose `roles` array contains the value in `X-User-Role`
and whose `employment_status` is `ACTIVE`. There are therefore no fixed user
ids — headers are built from ids minted by the API at run time, which is what
the `make_*_headers` builders below are for.

The single exemption is staff-member creation, which does not resolve the
acting identity, so the first `FacilitiesDirector` row can be bootstrapped into
an empty database with `BOOTSTRAP_USER_ID`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Identity used only for the bootstrap `POST /turf/staff-members` call.
BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000000"

#: Canonical staff roster used by the fixtures, keyed by a short handle.
#: `id` is deliberately absent: it is minted by the API and threaded at run time.
TEST_USERS = {
    "director": {
        "full_name": "Dana Reyes",
        "roles": [Role.FACILITIES_DIRECTOR],
        "role": Role.FACILITIES_DIRECTOR,
    },
    "director_two": {
        "full_name": "Marcus Hale",
        "roles": [Role.FACILITIES_DIRECTOR],
        "role": Role.FACILITIES_DIRECTOR,
    },
    "inspector": {
        "full_name": "Ines Vargas",
        "roles": [Role.SAFETY_INSPECTOR],
        "role": Role.SAFETY_INSPECTOR,
    },
    "inspector_two": {
        "full_name": "Hugo Bertrand",
        "roles": [Role.SAFETY_INSPECTOR],
        "role": Role.SAFETY_INSPECTOR,
    },
    "agronomist": {
        "full_name": "Tobias Lund",
        "roles": [Role.TURF_AGRONOMIST],
        "role": Role.TURF_AGRONOMIST,
    },
    "agronomist_two": {
        "full_name": "Selma Aziz",
        "roles": [Role.TURF_AGRONOMIST],
        "role": Role.TURF_AGRONOMIST,
    },
    "cert_officer": {
        "full_name": "Cyril Okafor",
        "roles": [Role.CERTIFICATION_OFFICER],
        "role": Role.CERTIFICATION_OFFICER,
    },
    "cert_officer_two": {
        "full_name": "Noor Haddad",
        "roles": [Role.CERTIFICATION_OFFICER],
        "role": Role.CERTIFICATION_OFFICER,
    },
    "coordinator": {
        "full_name": "Priya Raman",
        "roles": [Role.FIELD_OPERATIONS_COORDINATOR],
        "role": Role.FIELD_OPERATIONS_COORDINATOR,
    },
    "coordinator_two": {
        "full_name": "Alan Whitby",
        "roles": [Role.FIELD_OPERATIONS_COORDINATOR],
        "role": Role.FIELD_OPERATIONS_COORDINATOR,
    },
}


def make_facilities_director_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `FacilitiesDirector` acting as the given staff member."""
    return build_user_headers(user_id, Role.FACILITIES_DIRECTOR)


def make_turf_agronomist_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `TurfAgronomist` acting as the given staff member."""
    return build_user_headers(user_id, Role.TURF_AGRONOMIST)


def make_safety_inspector_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `SafetyInspector` acting as the given staff member."""
    return build_user_headers(user_id, Role.SAFETY_INSPECTOR)


def make_certification_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `CertificationOfficer` acting as the given staff member."""
    return build_user_headers(user_id, Role.CERTIFICATION_OFFICER)


def make_field_operations_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `FieldOperationsCoordinator` acting as the given staff member."""
    return build_user_headers(user_id, Role.FIELD_OPERATIONS_COORDINATOR)


def make_bootstrap_director_headers() -> Dict[str, str]:
    """Headers for the one call that is exempt from identity resolution."""
    return build_user_headers(BOOTSTRAP_USER_ID, Role.FACILITIES_DIRECTOR)


#: Builder lookup by role name, useful for parametrised authorisation checks.
HEADER_BUILDERS = {
    Role.FACILITIES_DIRECTOR: make_facilities_director_headers,
    Role.TURF_AGRONOMIST: make_turf_agronomist_headers,
    Role.SAFETY_INSPECTOR: make_safety_inspector_headers,
    Role.CERTIFICATION_OFFICER: make_certification_officer_headers,
    Role.FIELD_OPERATIONS_COORDINATOR: make_field_operations_coordinator_headers,
}
