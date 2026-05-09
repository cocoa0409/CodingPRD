"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- Customer:       opaque identity. X-User-ID is the insured-party id;
                  ownership is via Claim.claimant_id == X-User-ID and via
                  Policy.insured_party_id == X-User-ID. The server does NOT
                  match X-User-ID to any entity's id.
- Adjuster:       entity_backed:Adjuster. X-User-ID is the actual Adjuster.id;
                  ownership checks compare Investigation.adjuster_id to
                  X-User-ID. Use make_adjuster_headers(adjuster["id"]) on any
                  ownership-gated call.
- Reviewer:       opaque identity. X-User-ID is recorded on
                  ReviewDecision.reviewer_id and used for segregation-of-duties
                  checks; not matched against any entity id.
- PayoutOfficer:  opaque identity. X-User-ID recorded on audit log only.
- PlatformAdmin:  opaque identity. X-User-ID recorded on audit log only;
                  admin-only endpoints additionally require X-Admin-Token.

For Adjuster, any test that exercises ownership / segregation-of-duties MUST
use the per-instance builder make_adjuster_headers(adjuster["id"]). The shared
TEST_USERS["adjuster_headers"] constant is reserved only for tests that do not
exercise ownership (e.g., 400-on-bad-payload, 404-on-missing-resource, or
RBAC-only checks).

For Customer, a per-instance builder make_customer_headers(insured_party_id)
exists as well — although Customer is opaque, ownership checks compare
X-User-ID against Policy.insured_party_id and Claim.claimant_id, so tests
must reuse the same opaque id across Policy creation (insured_party_id)
and the subsequent claim filing.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import DEFAULTS


# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership or segregation of duties.
TEST_USERS = {
    # PlatformAdmin (opaque) — additionally needs X-Admin-Token on the
    # /_clock/* and /_events/* endpoints; admin_token_headers below carries it.
    "admin_headers": {
        **build_user_headers("test-admin-1", "PlatformAdmin"),
    },

    # PlatformAdmin with the admin token attached (for /_clock/* and /_events/*).
    "admin_token_headers": {
        **build_user_headers("test-admin-1", "PlatformAdmin"),
        "X-Admin-Token": DEFAULTS["ADMIN_TOKEN"],
    },

    # Reviewer (opaque) — distinct labels for tests that need two distinct
    # reviewer principals (segregation of duties).
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "reviewer_b_headers": build_user_headers("test-reviewer-2", "Reviewer"),

    # PayoutOfficer (opaque)
    "payout_officer_headers": build_user_headers("test-payout-officer-1", "PayoutOfficer"),

    # Customer (opaque) — placeholder shared constant for non-ownership tests
    # (e.g., 400-on-bad-payload, RBAC, 404-on-missing-resource). For
    # ownership-gated calls (POST /claims, GET /claims/{id}, etc.), use
    # make_customer_headers(insured_party_id) so Policy.insured_party_id and
    # Claim.claimant_id resolve to the same opaque id throughout the test.
    "customer_headers": build_user_headers("test-customer-placeholder", "Customer"),

    # Adjuster (entity_backed) — placeholder shared constant for tests that
    # do NOT exercise ownership (e.g., 400-on-bad-payload, RBAC, 404 on
    # missing claim). For ownership-gated calls, use
    # make_adjuster_headers(adjuster["id"]) so Investigation.adjuster_id ==
    # X-User-ID can hold.
    "adjuster_headers": build_user_headers("test-adjuster-placeholder", "Adjuster"),
}


def make_adjuster_headers(adjuster_id: str) -> dict:
    """For Adjuster (entity_backed:Adjuster). Pass the actual Adjuster.id as
    user_id whenever the call is ownership- or segregation-gated (notably any
    POST under /claims/{id}/investigations* and /claims/{id}/submit-for-review,
    where Investigation.adjuster_id must equal X-User-ID, and where the
    primary reviewer must differ from this id)."""
    return build_user_headers(adjuster_id, "Adjuster")


def make_customer_headers(insured_party_id: str) -> dict:
    """For Customer (opaque). The id is recorded on Claim.claimant_id at
    intake and on Appeal.requestor_id at appeal creation, and is compared
    against Policy.insured_party_id; tests must thread the SAME opaque id
    through Policy creation and the customer's subsequent calls."""
    return build_user_headers(insured_party_id, "Customer")


def make_reviewer_headers(label: str = "reviewer") -> dict:
    """For Reviewer (opaque). The X-User-ID is recorded on ReviewDecision
    rows and compared for segregation-of-duties (must differ from
    Investigation.adjuster_id at primary review, and must differ from both
    Investigation.adjuster_id and the primary reviewer_id at secondary
    review). Use distinct labels to obtain distinct principals."""
    return build_user_headers(f"test-{label}", "Reviewer")


def make_payout_officer_headers(label: str = "payout-officer") -> dict:
    """For PayoutOfficer (opaque). The X-User-ID is recorded on audit log
    actor_id but never matched against an entity id."""
    return build_user_headers(f"test-{label}", "PayoutOfficer")


def make_admin_headers(label: str = "admin", with_token: bool = False) -> dict:
    """For PlatformAdmin (opaque). Pass with_token=True for the /_clock/*
    and /_events/* control endpoints, which additionally require X-Admin-Token."""
    headers = build_user_headers(f"test-{label}", "PlatformAdmin")
    if with_token:
        headers = {**headers, "X-Admin-Token": DEFAULTS["ADMIN_TOKEN"]}
    return headers
