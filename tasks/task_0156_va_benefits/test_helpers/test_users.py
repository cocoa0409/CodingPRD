"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When X-User-Role is Veteran, X-User-ID is the id of the acting
    Veteran entity; every ownership check on a resource that references a
    veteran (a Claim, an Enrollment, a Dependent, a VocRehabPlan, or a
    PaymentLedgerEntry) compares the resource's veteran_id field to
    X-User-ID, and any ownership mismatch is treated as a forbidden
    operation. When X-User-Role is VAClerk, Rater, Counselor, or
    PlatformAdmin, X-User-ID is an opaque operator identifier not tied
    to any persisted entity."

The shared *_headers constants below are appropriate ONLY for:

    * Veteran-role tests whose success does NOT depend on the caller
      owning the subject resource (auth probes, 404-on-missing-veteran
      probes, RBAC probes).
    * The four opaque roles (VAClerk, Rater, Counselor, PlatformAdmin),
      where X-User-ID is never compared against any entity id.

For any Veteran-scoped operation whose acceptance depends on the caller
being the resource owner (POST /claims with veteran_id, POST
/enrollments with veteran_id, POST /enrollments/{id}/withdraw, POST
/claims/{id}/appeal, GET /veterans/{id} as self, etc.), tests and
fixtures MUST mint headers via make_veteran_headers(veteran_id) with
the real Veteran.id returned by POST /veterans.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — safe for opaque roles and non-ownership Veteran tests.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Veteran — shared constant is reserved for non-ownership
    # tests (auth probes, 404 probes, RBAC probes that do not require the
    # caller's id to match a resource's veteran_id).
    "veteran_headers": build_user_headers("veteran-shared-0001", "Veteran"),
    # Opaque operator roles — X-User-ID is not compared to any entity.
    "va_clerk_headers": build_user_headers("va-clerk-0001", "VAClerk"),
    "va_clerk_2_headers": build_user_headers("va-clerk-0002", "VAClerk"),
    "rater_headers": build_user_headers("rater-0001", "Rater"),
    "rater_2_headers": build_user_headers("rater-0002", "Rater"),
    "rater_3_headers": build_user_headers("rater-0003", "Rater"),
    "counselor_headers": build_user_headers("counselor-0001", "Counselor"),
    "counselor_2_headers": build_user_headers("counselor-0002", "Counselor"),
    "counselor_3_headers": build_user_headers("counselor-0003", "Counselor"),
    "platform_admin_headers": build_user_headers(
        "platform-admin-0001", "PlatformAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Veteran role
# whenever the downstream call is ownership-gated.
#
# PRD §2.1: "When X-User-Role is Veteran, X-User-ID is the id of the
# acting Veteran entity; every ownership check on a resource that
# references a veteran ... compares the resource's veteran_id field to
# X-User-ID, and any ownership mismatch is treated as a forbidden
# operation."
# ---------------------------------------------------------------------------
def make_veteran_headers(veteran_id: str) -> Dict[str, str]:
    """Headers for a specific Veteran. Use this whenever the call is
    ownership-gated — i.e. any operation where the server must verify
    the caller is the owning Veteran (POST /claims with veteran_id ==
    caller, POST /enrollments with veteran_id == caller, POST
    /claims/{id}/appeal, POST /enrollments/{id}/withdraw, GET
    /veterans/{id} as self, GET /veterans/{id}/ledger, etc.).
    """
    return build_user_headers(veteran_id, "Veteran")


def make_va_clerk_headers(
    operator_id: str = "va-clerk-0001",
) -> Dict[str, str]:
    """Headers for a VAClerk operator. PRD §2.1 declares this role
    opaque; the operator_id is not compared to any entity's id."""
    return build_user_headers(operator_id, "VAClerk")


def make_rater_headers(operator_id: str = "rater-0001") -> Dict[str, str]:
    """Headers for a Rater operator. Opaque role per PRD §2.1. The
    operator_id supplied here is the value that ends up in Claim.rater_id
    after /start-review, so segregation-of-duties tests construct two
    raters by passing two distinct operator_ids."""
    return build_user_headers(operator_id, "Rater")


def make_counselor_headers(
    operator_id: str = "counselor-0001",
) -> Dict[str, str]:
    """Headers for a Counselor operator. Opaque role per PRD §2.1. The
    operator_id supplied here is the value that ends up in
    VocRehabPlan.counselor_id after /approve, so the resume-vs-approve
    segregation check distinguishes counselors by passing distinct
    operator_ids."""
    return build_user_headers(operator_id, "Counselor")


def make_platform_admin_headers(
    operator_id: str = "platform-admin-0001",
) -> Dict[str, str]:
    """Headers for a PlatformAdmin. Opaque role per PRD §2.1; holds the
    test-driving clock-advance and sweep capabilities."""
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_veteran_headers",
    "make_va_clerk_headers",
    "make_rater_headers",
    "make_counselor_headers",
    "make_platform_admin_headers",
]
