"""Pre-built role headers for every role in the Agri-Traceability API.

PRD §2.1 distinguishes identity-backed roles from opaque roles:

  Identity-backed (X-User-ID is compared to a stored field):
    - Grower:      X-User-ID is matched against PlantingBatch.grower_id.
                   A grower may only operate on planting batches whose grower_id
                   equals their own X-User-ID.
    - Distributor: X-User-ID is matched against LogisticsLeg.to_party_id (for
                   acknowledge) and against the distributor_id field on a disposal
                   record. PRD §2.10: "A Distributor who acknowledges a leg must
                   be the leg's destination party — the acknowledger's X-User-ID
                   must equal to_party_id. A Distributor who records a disposal
                   must supply a distributor_id matching their own X-User-ID."

  Opaque (X-User-ID is recorded but never compared to an entity id):
    - Inspector, RegulatoryOfficer, LogisticsOperator, Consumer

Consequence for fixtures: any owner-gated call by Grower or Distributor MUST
use the per-instance builder (make_grower_headers / make_distributor_headers)
keyed on the actual id used at the resource's creation. Falling back to the
shared TEST_USERS constant for those owner-gated calls reproduces the canonical
bug in which X-User-ID never equals any real entity id and every ownership
check rejects every request.
"""
from prd_bench_local_runner.testing import build_user_headers


# Default opaque ids used by fixtures.
DEFAULT_GROWER_ID = "user-grower-001"
DEFAULT_GROWER_ID_ALT = "user-grower-002"
DEFAULT_DISTRIBUTOR_ID = "user-distributor-001"


# Shared constants — safe for opaque roles, and for tests that do NOT exercise
# ownership (e.g., 400-on-bad-payload, 404-on-missing-resource, role-only RBAC
# negative tests). For ownership-gated calls on Grower or Distributor, use the
# per-instance builders below instead.
TEST_USERS = {
    # Grower (entity_backed): shared default — fixtures that create batches use
    # DEFAULT_GROWER_ID as grower_id, so this header pair is owner-correct for
    # those batches.
    "grower_headers": build_user_headers(DEFAULT_GROWER_ID, "Grower"),
    "grower_headers_alt": build_user_headers(DEFAULT_GROWER_ID_ALT, "Grower"),

    # Distributor (entity_backed): shared constant. Owner-gated calls (acknowledge
    # a leg, post a disposal) MUST instead use make_distributor_headers(<id>) so
    # X-User-ID equals the to_party_id/distributor_id used at write time.
    "distributor_headers": build_user_headers(DEFAULT_DISTRIBUTOR_ID, "Distributor"),

    # Opaque roles — shared constants are canonical.
    "inspector_headers": build_user_headers("user-inspector-001", "Inspector"),
    "inspector_headers_alt": build_user_headers("user-inspector-002", "Inspector"),
    "regulatory_headers": build_user_headers("user-regulatory-001", "RegulatoryOfficer"),
    "logistics_headers": build_user_headers("user-logistics-001", "LogisticsOperator"),
    "consumer_headers": build_user_headers("user-consumer-001", "Consumer"),
}


# --- Per-instance builders ---
# Required for every entity_backed role per the skill's identity-threading rule.

def make_grower_headers(user_id: str) -> dict:
    """Build Grower headers whose X-User-ID equals the supplied user_id.

    Per PRD §2.1, "a grower may only operate on planting batches whose grower_id
    matches their own X-User-ID". Pass the same id that was set as the batch's
    grower_id at creation time.
    """
    return build_user_headers(user_id, "Grower")


def make_distributor_headers(user_id: str) -> dict:
    """Build Distributor headers whose X-User-ID equals the supplied user_id.

    Per PRD §2.1 / §2.10, a distributor's X-User-ID is compared to
    LogisticsLeg.to_party_id (for acknowledge) and to the disposal's
    distributor_id. Pass the Distributor.id that was registered and used as
    to_party_id / distributor_id.
    """
    return build_user_headers(user_id, "Distributor")


def make_inspector_headers(user_id: str) -> dict:
    """Build Inspector headers — PRD §2.1 records X-User-ID as inspector_id."""
    return build_user_headers(user_id, "Inspector")


def make_regulatory_headers(user_id: str = "user-regulatory-001") -> dict:
    return build_user_headers(user_id, "RegulatoryOfficer")


def make_logistics_headers(user_id: str = "user-logistics-001") -> dict:
    return build_user_headers(user_id, "LogisticsOperator")


def make_consumer_headers(user_id: str = "user-consumer-001") -> dict:
    return build_user_headers(user_id, "Consumer")
