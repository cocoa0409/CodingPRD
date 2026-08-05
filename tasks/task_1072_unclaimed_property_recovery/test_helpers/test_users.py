"""Pre-built role headers for every role in the PRD (§2.1).

The six roles are StateAdmin, Holder, Owner, RecoveryAgent, StateExaminer, and
StateApprover. StateAdmin/StateExaminer/StateApprover are opaque operator
identifiers not tied to any persisted entity; their X-User-ID is recorded (as
examiner_user_id / approver_user_id / reviewed_by_user_id) and compared only to
each other (segregation of duties, §2.10), never to an entity id.

Holder, Owner, and RecoveryAgent are entity_backed: X-User-ID is the acting
Holder.id / Owner.id / RecoveryFirm.id respectively, and ownership checks compare
a resource's foreign key to it. For any ownership-gated call, the per-instance
builders below MUST be given the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Default opaque operator ids used across setups.
DEFAULT_EXAMINER_ID = "exam-1"
DEFAULT_APPROVER_ID = "appr-1"
DEFAULT_ADMIN_ID = "admin-1"

TEST_USERS = {
    # opaque roles — canonical shared constants
    "state_admin_headers": build_user_headers(DEFAULT_ADMIN_ID, "StateAdmin"),
    "state_examiner_headers": build_user_headers(DEFAULT_EXAMINER_ID, "StateExaminer"),
    "state_approver_headers": build_user_headers(DEFAULT_APPROVER_ID, "StateApprover"),
    # entity_backed fallbacks — non-ownership tests only (401/403/404 shape checks)
    "holder_headers": build_user_headers("holder-shared", "Holder"),
    "owner_headers": build_user_headers("owner-shared", "Owner"),
    "recovery_agent_headers": build_user_headers("firm-shared", "RecoveryAgent"),
}


# --- Per-instance builders for entity_backed roles (mandatory for ownership) ---
def make_holder_headers(user_id: str) -> dict:
    """Holder role (entity_backed:Holder). Pass the acting Holder.id — compared to
    a Property/HolderReport/AuditCase holder foreign key for ownership."""
    return build_user_headers(user_id, "Holder")


def make_owner_headers(user_id: str) -> dict:
    """Owner role (entity_backed:Owner). Pass the acting Owner.id — compared to a
    Claim.claimant_owner_id for ownership."""
    return build_user_headers(user_id, "Owner")


def make_recovery_agent_headers(user_id: str) -> dict:
    """RecoveryAgent role (entity_backed:RecoveryFirm). Pass the acting
    RecoveryFirm.id — compared to a Claim.recovery_firm_id for ownership."""
    return build_user_headers(user_id, "RecoveryAgent")


# --- Opaque-role builders that let a test pin the exact X-User-ID (for SoD) ---
def make_admin_headers(user_id: str = DEFAULT_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "StateAdmin")


def make_examiner_headers(user_id: str = DEFAULT_EXAMINER_ID) -> dict:
    return build_user_headers(user_id, "StateExaminer")


def make_approver_headers(user_id: str = DEFAULT_APPROVER_ID) -> dict:
    return build_user_headers(user_id, "StateApprover")
