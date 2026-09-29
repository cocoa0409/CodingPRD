"""Actor identities and per-role header builders.

Two of the six roles read ``X-User-ID`` as the id of a persisted row, so their
headers must be built per instance from an id the test actually created:

* ``InfusionNurse`` — ``X-User-ID`` is the id of the acting ``Nurse`` row.
* ``Patient``       — ``X-User-ID`` is the id of the acting ``Patient`` row.

The other four roles carry an opaque operator identifier that the server never
compares to any entity id, so a shared constant is correct for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Opaque operator identifiers for the four roles that own no entity row.
TEST_USERS = {
    Role.SCHEDULER: "11111111-1111-1111-1111-111111111111",
    Role.PHARMACIST: "22222222-2222-2222-2222-222222222222",
    Role.AUTHORIZATION_SPECIALIST: "33333333-3333-3333-3333-333333333333",
    Role.MEDICAL_DIRECTOR: "44444444-4444-4444-4444-444444444444",
}

#: Placeholder ids for the two entity-backed roles. Only ever correct for calls
#: that perform no ownership comparison; ownership-gated calls must use the
#: per-instance builders below.
UNKNOWN_NURSE_ID = "55555555-5555-5555-5555-555555555555"
UNKNOWN_PATIENT_ID = "66666666-6666-6666-6666-666666666666"


def make_scheduler_headers() -> Dict[str, str]:
    return build_user_headers(TEST_USERS[Role.SCHEDULER], Role.SCHEDULER)


def make_pharmacist_headers() -> Dict[str, str]:
    return build_user_headers(TEST_USERS[Role.PHARMACIST], Role.PHARMACIST)


def make_auth_specialist_headers() -> Dict[str, str]:
    return build_user_headers(
        TEST_USERS[Role.AUTHORIZATION_SPECIALIST], Role.AUTHORIZATION_SPECIALIST
    )


def make_medical_director_headers() -> Dict[str, str]:
    return build_user_headers(TEST_USERS[Role.MEDICAL_DIRECTOR], Role.MEDICAL_DIRECTOR)


def make_nurse_headers(user_id: str) -> Dict[str, str]:
    """Headers for the ``InfusionNurse`` whose ``Nurse`` row id is ``user_id``."""
    return build_user_headers(user_id, Role.INFUSION_NURSE)


def make_infusion_nurse_headers(user_id: str) -> Dict[str, str]:
    """Alias of :func:`make_nurse_headers` spelled with the full role name."""
    return make_nurse_headers(user_id)


def make_patient_headers(user_id: str) -> Dict[str, str]:
    """Headers for the ``Patient`` whose ``Patient`` row id is ``user_id``."""
    return build_user_headers(user_id, Role.PATIENT)


#: Pre-built headers for the four opaque-identity roles.
SCHEDULER = make_scheduler_headers()
PHARMACIST = make_pharmacist_headers()
AUTH_SPECIALIST = make_auth_specialist_headers()
MEDICAL_DIRECTOR = make_medical_director_headers()


def headers_for_role(role: str, user_id: str = None) -> Dict[str, str]:
    """Build headers for any role, requiring ``user_id`` for the two owned roles."""
    if role in (Role.INFUSION_NURSE, Role.PATIENT):
        if user_id is None:
            raise ValueError(f"role {role} needs the id of its backing row")
        return build_user_headers(user_id, role)
    return build_user_headers(user_id or TEST_USERS.get(role, "unknown"), role)
