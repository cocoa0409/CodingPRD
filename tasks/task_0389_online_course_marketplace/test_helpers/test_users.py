"""Pre-built role headers for every role in the PRD (PRD §2.1).

The PRD recognizes exactly four roles, spelled precisely: Anonymous, Instructor,
Learner, PlatformAdmin.

- Anonymous and PlatformAdmin are OPAQUE-identity roles: X-User-ID is an opaque
  identifier the server never compares to a stored entity id. For these, the shared
  constants are the canonical form.
- Instructor and Learner are ENTITY-BACKED: X-User-ID is the acting entity's id, and
  ownership checks compare a resource's instructor_id / learner_id against X-User-ID.
  For ownership-gated calls, callers MUST build headers with the real entity id via
  make_instructor_headers(instructor_id) / make_learner_headers(learner_id); the shared
  constants carry a fake id usable only for non-ownership paths (401/403/404).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Entity-backed roles — fake-id fallbacks for non-ownership tests only.
    "instructor_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000a1", "Instructor"
    ),
    "learner_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000b2", "Learner"
    ),
}


def make_instructor_headers(instructor_id: str) -> dict:
    """Headers for the Instructor role bound to a specific Instructor.id.

    Pass the real Instructor.id whenever the call is ownership-gated (creating courses,
    lessons, coupons, bundles, payouts on resources that carry that instructor_id) — per
    PRD §2.1 the server compares X-User-ID against the resource's instructor_id."""
    return build_user_headers(instructor_id, "Instructor")


def make_learner_headers(learner_id: str) -> dict:
    """Headers for the Learner role bound to a specific Learner.id.

    Pass the real Learner.id whenever the call is ownership-gated (enroll, refund,
    lesson-completion, review, retract) — per PRD §2.1 the server compares X-User-ID
    against the enrollment's learner_id."""
    return build_user_headers(learner_id, "Learner")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """Headers for the PlatformAdmin role (opaque id)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Headers for the Anonymous role (opaque id)."""
    return build_user_headers(user_id, "Anonymous")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
