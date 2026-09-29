"""Pre-built operator headers for every role the PRD recognises.

Two of the five roles are backed by a persisted entity: a `DonorRegistryLiaison`
sends the acting `Registry.id` as `X-User-ID`, and a `CollectionCenterOps`
operator sends the acting `CollectionCenter.id`.  Those two roles MUST be built
per instance with `make_liaison_headers(registry_id)` /
`make_center_ops_headers(center_id)`; the shared constants below are only usable
for calls that never reach an ownership comparison (bad payloads, unknown ids).

The other three roles are opaque operator identifiers, so their shared constants
are the canonical form.  Two distinct physician identities are provided because
the collection-method decision requires a second physician.
"""
from prd_bench_local_runner.testing import build_user_headers

COORDINATOR_USER_ID = "tc-1"
OTHER_COORDINATOR_USER_ID = "tc-2"
PHYSICIAN_USER_ID = "md-1"
SECOND_PHYSICIAN_USER_ID = "md-2"
OPERATIONS_USER_ID = "ops-1"

TEST_USERS = {
    "coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "TransplantCoordinator"),
    "other_coordinator_headers": build_user_headers(
        OTHER_COORDINATOR_USER_ID, "TransplantCoordinator"
    ),
    "physician_headers": build_user_headers(PHYSICIAN_USER_ID, "MedicalDirector"),
    "second_physician_headers": build_user_headers(
        SECOND_PHYSICIAN_USER_ID, "MedicalDirector"
    ),
    "operations_headers": build_user_headers(OPERATIONS_USER_ID, "RegistryOperations"),
    # entity_backed roles: fallbacks for non-ownership tests only.
    "liaison_headers": build_user_headers("liaison-unbound", "DonorRegistryLiaison"),
    "center_ops_headers": build_user_headers("center-unbound", "CollectionCenterOps"),
}


def make_liaison_headers(registry_id: str) -> dict:
    """Headers for a DonorRegistryLiaison acting for the given registry.

    Pass the real `Registry.id`: every donor-scoped write compares the target
    donor's `registry_id` against `X-User-ID`.
    """
    return build_user_headers(registry_id, "DonorRegistryLiaison")


def make_center_ops_headers(center_id: str) -> dict:
    """Headers for a CollectionCenterOps operator acting for the given centre.

    Pass the real `CollectionCenter.id`: every booking write compares the
    booking's `collection_center_id` against `X-User-ID`.
    """
    return build_user_headers(center_id, "CollectionCenterOps")


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for an arbitrary TransplantCoordinator operator identifier."""
    return build_user_headers(user_id, "TransplantCoordinator")


def make_physician_headers(user_id: str) -> dict:
    """Headers for an arbitrary MedicalDirector operator identifier."""
    return build_user_headers(user_id, "MedicalDirector")


def make_operations_headers(user_id: str = OPERATIONS_USER_ID) -> dict:
    """Headers for an arbitrary RegistryOperations operator identifier."""
    return build_user_headers(user_id, "RegistryOperations")


ROLE_NAMES = [
    "TransplantCoordinator",
    "DonorRegistryLiaison",
    "MedicalDirector",
    "CollectionCenterOps",
    "RegistryOperations",
]
