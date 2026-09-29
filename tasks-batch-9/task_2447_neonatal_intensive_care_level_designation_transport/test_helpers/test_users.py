"""Caller identities and header builders.

The PRD splits the seven roles in two. `NetworkAdmin`, `TransportCoordinator`,
`BedsideNurse` and `FollowUpCoordinator` carry an opaque `X-User-ID`, so they can
be modelled by fixed constants. `UnitDirector`, `IntakeNeonatologist` and
`ReferringClinician` are unit-scoped: their `X-User-ID` must read
`<unit_id>:<person-label>`, where the unit portion is compared by ownership
checks and the person portion is compared by the segregation-of-duties rules.
Those three roles therefore have builders that take the unit id created by the
test, and tests must never send a hard-coded identifier for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque, non-unit-scoped identities
# ---------------------------------------------------------------------------

TEST_USERS = {
    "network_admin": {"user_id": "net-1", "role": UserRole.NETWORK_ADMIN.value},
    "network_admin_2": {"user_id": "net-2", "role": UserRole.NETWORK_ADMIN.value},
    "transport_coordinator": {
        "user_id": "coord-1",
        "role": UserRole.TRANSPORT_COORDINATOR.value,
    },
    "transport_coordinator_2": {
        "user_id": "coord-2",
        "role": UserRole.TRANSPORT_COORDINATOR.value,
    },
    "bedside_nurse": {"user_id": "nurse-1", "role": UserRole.BEDSIDE_NURSE.value},
    "bedside_nurse_2": {"user_id": "nurse-2", "role": UserRole.BEDSIDE_NURSE.value},
    "bedside_nurse_3": {"user_id": "nurse-3", "role": UserRole.BEDSIDE_NURSE.value},
    "followup_coordinator": {
        "user_id": "fu-1",
        "role": UserRole.FOLLOWUP_COORDINATOR.value,
    },
    "followup_coordinator_2": {
        "user_id": "fu-2",
        "role": UserRole.FOLLOWUP_COORDINATOR.value,
    },
}


def _headers(key: str) -> Dict[str, str]:
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def make_network_admin_headers(person: str = "net-1") -> Dict[str, str]:
    return build_user_headers(person, UserRole.NETWORK_ADMIN.value)


def make_transport_coordinator_headers(person: str = "coord-1") -> Dict[str, str]:
    return build_user_headers(person, UserRole.TRANSPORT_COORDINATOR.value)


def make_bedside_nurse_headers(person: str = "nurse-1") -> Dict[str, str]:
    return build_user_headers(person, UserRole.BEDSIDE_NURSE.value)


def make_followup_coordinator_headers(person: str = "fu-1") -> Dict[str, str]:
    return build_user_headers(person, UserRole.FOLLOWUP_COORDINATOR.value)


# ---------------------------------------------------------------------------
# Unit-scoped identities: `<unit_id>:<person-label>`
# ---------------------------------------------------------------------------


def make_unit_scoped_user_id(unit_id: str, person: str) -> str:
    return f"{unit_id}:{person}"


def make_unit_director_headers(unit_id: str, person: str = "dir-1") -> Dict[str, str]:
    return build_user_headers(
        make_unit_scoped_user_id(unit_id, person), UserRole.UNIT_DIRECTOR.value
    )


def make_intake_neonatologist_headers(unit_id: str, person: str = "intake-1") -> Dict[str, str]:
    return build_user_headers(
        make_unit_scoped_user_id(unit_id, person), UserRole.INTAKE_NEONATOLOGIST.value
    )


def make_referring_clinician_headers(unit_id: str, person: str = "ref-1") -> Dict[str, str]:
    return build_user_headers(
        make_unit_scoped_user_id(unit_id, person), UserRole.REFERRING_CLINICIAN.value
    )


# ---------------------------------------------------------------------------
# Convenience header sets for the opaque roles
# ---------------------------------------------------------------------------

NETWORK_ADMIN_HEADERS = _headers("network_admin")
NETWORK_ADMIN_2_HEADERS = _headers("network_admin_2")
TRANSPORT_COORDINATOR_HEADERS = _headers("transport_coordinator")
BEDSIDE_NURSE_HEADERS = _headers("bedside_nurse")
BEDSIDE_NURSE_2_HEADERS = _headers("bedside_nurse_2")
FOLLOWUP_COORDINATOR_HEADERS = _headers("followup_coordinator")
