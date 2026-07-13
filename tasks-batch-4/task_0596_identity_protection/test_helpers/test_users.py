"""Pre-built role headers for every role in the PRD (§2.1).

`Subscriber` and `RestorationSpecialist` are entity-backed: their `X-User-ID` must be the
actual Subscriber.id / Specialist.id of the entity that owns the target resource. Always use
the per-instance builders below for those two roles whenever a call is ownership-gated.

`PlatformAdmin` and `ClaimsAdjuster` carry opaque operator ids; `Anonymous` carries none at all.
"""

from prd_bench_local_runner.testing import build_user_headers


def _role_only_headers(role: str) -> dict:
    """Headers carrying X-User-Role but deliberately no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# Shared constants — safe for opaque roles and for calls that exercise no ownership check.
TEST_USERS = {
    # Anonymous: no X-User-ID is required or interpreted.
    "anonymous_headers": _role_only_headers("Anonymous"),
    # Opaque operator ids.
    "admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "admin_alt_headers": build_user_headers("admin-002", "PlatformAdmin"),
    "adjuster_headers": build_user_headers("adjuster-001", "ClaimsAdjuster"),
    "adjuster_alt_headers": build_user_headers("adjuster-002", "ClaimsAdjuster"),
    # Entity-backed fallbacks — only for tests that do NOT depend on owning the resource
    # (e.g. 404-on-missing-resource, 400-on-bad-payload).
    "subscriber_headers": build_user_headers(
        "99999999-8888-4777-8666-555555555555", "Subscriber"
    ),
    "specialist_headers": build_user_headers(
        "88888888-7777-4666-8555-444444444444", "RestorationSpecialist"
    ),
}


# ─── Per-instance builders (mandatory for entity-backed roles) ────────────────

def make_subscriber_headers(subscriber_id: str) -> dict:
    """Headers for the Subscriber role. Pass the real Subscriber.id."""
    return build_user_headers(subscriber_id, "Subscriber")


def make_specialist_headers(specialist_id: str) -> dict:
    """Headers for the RestorationSpecialist role. Pass the real Specialist.id."""
    return build_user_headers(specialist_id, "RestorationSpecialist")


def make_admin_headers(user_id: str) -> dict:
    """Headers for PlatformAdmin with a chosen opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_adjuster_headers(user_id: str) -> dict:
    """Headers for ClaimsAdjuster with a chosen opaque operator id."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_role_only_headers(role: str) -> dict:
    """Headers with X-User-Role set and X-User-ID omitted entirely."""
    return _role_only_headers(role)