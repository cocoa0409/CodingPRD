"""Pre-built role headers for every role in the wire service PRD.

Six roles (PlatformAdmin, SalesOps, Editor, Legal, Auditor, Billing) use an
opaque operator identifier for X-User-ID; the shared constants below are their
canonical form.

SubscriberRep is entity-backed: X-User-ID must be the id of the acting
Subscriber, because ownership checks compare a resource's subscriber foreign
key against X-User-ID. Any call that is ownership-gated (recording a
republication, reading own data) MUST use make_subscriberrep_headers() with
the actual Subscriber.id — never the shared fallback constant, whose user id
matches no real subscriber.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "salesops_headers": build_user_headers("test-salesops-1", "SalesOps"),
    "editor_headers": build_user_headers("test-editor-1", "Editor"),
    "legal_headers": build_user_headers("test-legal-1", "Legal"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "billing_headers": build_user_headers("test-billing-1", "Billing"),
    # Fallback only — valid solely where no ownership check applies.
    "subscriberrep_headers": build_user_headers("test-subscriberrep-1", "SubscriberRep"),
}


def make_subscriberrep_headers(subscriber_id: str) -> dict:
    """Headers for SubscriberRep calls. Pass the acting Subscriber's id so the
    cross-account ownership check (subscriber FK == X-User-ID) resolves."""
    return build_user_headers(subscriber_id, "SubscriberRep")
