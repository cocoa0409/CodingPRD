"""Pre-built role headers for every role in the PRD.

Five of the seven roles carry opaque identity: `ProgramAdmin`,
`WarrantyAdjudicator`, `TelematicsGateway`, `IndependentLab` and
`RegulatoryLiaison` present an operator identifier the server stores but never
compares against a record's `id`. Two roles are entity backed:

* `ServiceTechnician` — `X-User-ID` must be the acting `Technician`'s `id`.
* `VehicleOwner`      — `X-User-ID` must be the acting `Vehicle`'s `id`.

Anything that reaches an identity comparison MUST therefore build its headers
with `make_technician_headers(technician_id)` or
`make_owner_headers(vehicle_id)`. The shared constants below are safe only for
calls that never reach one — a 401/403 rejection, a not-found path, or a read.

Two distinct adjudicator identifiers are provided because dispute resolution
requires a resolver different from the adjudicator who decided the claim.
"""

from prd_bench_local_runner.testing import build_user_headers

ADJUDICATOR_1_ID = "adj-001"
ADJUDICATOR_2_ID = "adj-002"
PROGRAM_ADMIN_ID = "admin-001"
GATEWAY_ID = "gw-001"
LAB_ID = "lab-001"
LIAISON_ID = "liaison-001"

TEST_USERS = {
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_ID, "ProgramAdmin"),
    "program_admin_2_headers": build_user_headers("admin-002", "ProgramAdmin"),
    "adjudicator_headers": build_user_headers(ADJUDICATOR_1_ID, "WarrantyAdjudicator"),
    "adjudicator_2_headers": build_user_headers(ADJUDICATOR_2_ID, "WarrantyAdjudicator"),
    "gateway_headers": build_user_headers(GATEWAY_ID, "TelematicsGateway"),
    "lab_headers": build_user_headers(LAB_ID, "IndependentLab"),
    "liaison_headers": build_user_headers(LIAISON_ID, "RegulatoryLiaison"),
    # Entity-backed fallbacks. Never use where identity is compared.
    "technician_headers": build_user_headers(
        "tech-not-a-real-record", "ServiceTechnician"
    ),
    "owner_headers": build_user_headers("veh-not-a-real-record", "VehicleOwner"),
}


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    """ProgramAdmin headers. Identity is opaque to the server."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_adjudicator_headers(user_id: str) -> dict:
    """WarrantyAdjudicator headers for a named adjudicator identifier.

    The identifier is persisted in a claim's `adjudicated_by_user_id` and in a
    dispute's `resolved_by_user_id`, and the two are compared to each other, so
    two-person tests must build both sides explicitly.
    """
    return build_user_headers(user_id, "WarrantyAdjudicator")


def make_technician_headers(technician_id: str) -> dict:
    """ServiceTechnician headers. `technician_id` MUST be a real Technician `id`."""
    return build_user_headers(technician_id, "ServiceTechnician")


def make_owner_headers(vehicle_id: str) -> dict:
    """VehicleOwner headers. `vehicle_id` MUST be the acting Vehicle's `id`."""
    return build_user_headers(vehicle_id, "VehicleOwner")


def make_gateway_headers(user_id: str = GATEWAY_ID) -> dict:
    """TelematicsGateway headers. Identity is opaque to the server."""
    return build_user_headers(user_id, "TelematicsGateway")


def make_lab_headers(user_id: str = LAB_ID) -> dict:
    """IndependentLab headers. Identity is opaque to the server."""
    return build_user_headers(user_id, "IndependentLab")


def make_liaison_headers(user_id: str = LIAISON_ID) -> dict:
    """RegulatoryLiaison headers. Identity is opaque to the server."""
    return build_user_headers(user_id, "RegulatoryLiaison")


def headers_without_actor(role: str) -> dict:
    """Role headers with `X-User-ID` removed, for the actor-required rule."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    """Headers carrying no role at all, for the unauthenticated rule."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


NO_HEADERS: dict = {"Content-Type": "application/json"}
