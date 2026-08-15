"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD user-context section): TransferCoordinator and Any are
opaque; SendingPhysician / ReceivingPhysician / QualityReviewer are backed by a
Physician id; BedManager is backed by the managed Facility's id. Ownership-gated
calls must use the make_* builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "TransferCoordinator"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # Entity-backed roles: shared fallbacks for tests that never exercise
    # ownership (bad-payload, not-found, or role-gate scenarios).
    "sending_physician_headers": build_user_headers("test-sending-physician-1", "SendingPhysician"),
    "receiving_physician_headers": build_user_headers("test-receiving-physician-1", "ReceivingPhysician"),
    "bed_manager_headers": build_user_headers("test-bed-manager-1", "BedManager"),
    "quality_reviewer_headers": build_user_headers("test-quality-reviewer-1", "QualityReviewer"),
}


def make_sending_physician_headers(physician_id: str) -> dict:
    """SendingPhysician is entity-backed by Physician: pass the physician's id."""
    return build_user_headers(physician_id, "SendingPhysician")


def make_receiving_physician_headers(physician_id: str) -> dict:
    """ReceivingPhysician is entity-backed by Physician: pass the physician's id."""
    return build_user_headers(physician_id, "ReceivingPhysician")


def make_bed_manager_headers(facility_id: str) -> dict:
    """BedManager is entity-backed by Facility: pass the managed facility's id."""
    return build_user_headers(facility_id, "BedManager")


def make_quality_reviewer_headers(physician_id: str) -> dict:
    """QualityReviewer is entity-backed by Physician: pass the physician's id."""
    return build_user_headers(physician_id, "QualityReviewer")
