"""Pre-built role headers for every role in the gym membership platform.

PRD §2.1 defines five roles: Member, Trainer, StoreManager, BillingAdmin, Any.

Member and Trainer are entity-backed — X-User-ID is compared to the corresponding
entity's id for ownership checks. Tests that exercise ownership-gated calls MUST
mint headers with the real entity id via make_member_headers / make_trainer_headers.

StoreManager, BillingAdmin, and Any are opaque — X-User-ID is recorded but not
used for ownership comparison, so a shared constant is safe.

The TEST_USERS shared constants are kept ONLY for tests whose success does NOT
depend on ownership: malformed-payload tests, role-not-permitted tests, plain
404-on-missing-resource probes.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — safe for opaque roles, and for tests that do NOT exercise
# ownership (auth-failure tests, plain 404 probes, role-forbidden probes).
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — X-User-ID is never compared to any entity id per PRD §2.1.
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "any_headers": build_user_headers("test-anon-1", "Any"),
    # Entity-backed fallbacks — only safe for non-ownership tests.
    "member_headers": build_user_headers("test-member-fallback", "Member"),
    "trainer_headers": build_user_headers("test-trainer-fallback", "Trainer"),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED for every entity-backed role whenever the call
# is ownership-gated. PRD §2.1 says: "When X-User-Role is Member, X-User-ID is the
# id of the acting Member entity" and ownership checks compare member_id to
# X-User-ID. Likewise for Trainer.
# ──────────────────────────────────────────────────────────


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Build Member headers where X-User-ID == Member.id. PRD §2.1: when X-User-Role
    is Member, X-User-ID is the id of the acting Member entity."""
    return build_user_headers(member_id, "Member")


def make_trainer_headers(trainer_id: str) -> Dict[str, str]:
    """Build Trainer headers where X-User-ID == Trainer.id. PRD §2.1: ownership
    comparisons match the resource's trainer_id to X-User-ID."""
    return build_user_headers(trainer_id, "Trainer")


def make_store_manager_headers(operator_id: str = "test-store-manager-1") -> Dict[str, str]:
    """Build StoreManager headers. X-User-ID is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "StoreManager")


def make_billing_admin_headers(
    operator_id: str = "test-billing-admin-1",
) -> Dict[str, str]:
    """Build BillingAdmin headers. X-User-ID is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "BillingAdmin")


def make_any_headers(opaque_id: str = "test-anon-1") -> Dict[str, str]:
    """Build Any-role (public/anonymous) headers. X-User-ID is opaque per PRD §2.1."""
    return build_user_headers(opaque_id, "Any")
