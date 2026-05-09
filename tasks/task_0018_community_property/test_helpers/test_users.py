"""Pre-built role headers for every role in the community property platform.

Per PRD §2.1 there are exactly four role names: PropertyManager, Owner,
MaintenanceStaff, CommitteeChair. Owner is entity-backed — its X-User-ID
must equal the acting Owner.id whenever the call is ownership-gated. The
other three roles are opaque per PRD §2.1.

Two forms are exposed for each role:

- TEST_USERS — a shared-constant entry, safe for tests that do NOT exercise
  ownership (auth-failure probes, plain 404 probes, opaque-role calls). For
  the entity-backed Owner role this is a *fallback only*; ownership-gated
  fixtures and tests MUST use make_owner_headers(<actual-owner-id>) so the
  X-User-ID column actually matches the resource's owner_id.

- make_<role>_headers(user_id) — per-instance builders. Mandatory for the
  Owner role on every ownership-gated call, and useful for the opaque roles
  whenever a test wants the X-User-ID stamped onto an audit row or onto
  WorkOrder.assigned_staff_id to be a known constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (e.g., auth-failure tests, 404 probes, forbidden-role
# probes). The Owner entry is a fallback only; never use it on calls that
# require X-User-ID to equal the Owner.id.
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — X-User-ID is never compared to any entity id per PRD §2.1.
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "maintenance_headers": build_user_headers("test-maint-1", "MaintenanceStaff"),
    "committee_chair_headers": build_user_headers("test-chair-1", "CommitteeChair"),
    # Entity-backed Owner fallback — only for tests that do NOT exercise ownership.
    "owner_headers": build_user_headers("test-owner-fallback", "Owner"),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED for the entity-backed Owner role whenever
# the call is ownership-gated. Pass the actual Owner.id as user_id so the
# server's ownership check resolves X-User-ID to the owning row.
# ──────────────────────────────────────────────────────────

def make_owner_headers(owner_id: str) -> Dict[str, str]:
    """Build Owner headers where X-User-ID == Owner.id. PRD §2.1: when X-User-Role
    is Owner, X-User-ID is the id of the acting Owner; ownership checks compare
    the resource's foreign-key field to X-User-ID."""
    return build_user_headers(owner_id, "Owner")


def make_property_manager_headers(staff_id: str = "test-pm-1") -> Dict[str, str]:
    """Build PropertyManager headers. PRD §2.1: PropertyManager is opaque — X-User-ID
    is recorded (e.g., as actor_id on an AuditEntry) but is not compared to any
    entity's id."""
    return build_user_headers(staff_id, "PropertyManager")


def make_maintenance_headers(staff_id: str = "test-maint-1") -> Dict[str, str]:
    """Build MaintenanceStaff headers. PRD §2.1: MaintenanceStaff is opaque, but
    once a work order is dispatched the server enforces an equality check between
    X-User-ID and the recorded assigned_staff_id on subsequent transitions —
    callers therefore pass the same staff_id used at dispatch time."""
    return build_user_headers(staff_id, "MaintenanceStaff")


def make_committee_chair_headers(chair_id: str = "test-chair-1") -> Dict[str, str]:
    """Build CommitteeChair headers. PRD §2.1: CommitteeChair is opaque — X-User-ID
    is not compared to any entity id."""
    return build_user_headers(chair_id, "CommitteeChair")
