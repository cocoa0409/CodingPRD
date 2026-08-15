"""Pre-built role headers for every role in the PRD (§2.1).

Provider and Editor are entity-backed roles: their X-User-ID must be the id of
the acting Provider/Editor entity. Fixtures MUST call the per-instance builders
below with the real entity id whenever the call is ownership-gated. The shared
constants are fallbacks for tests that never exercise ownership (bad-payload
400s, missing-resource 404s, opaque-role calls).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "vendor_admin_headers": build_user_headers("vendor-admin-01", "VendorAdmin"),
    "client_admin_headers": build_user_headers("client-admin-01", "ClientAdmin"),
    "qa_supervisor_headers": build_user_headers("qa-01", "QASupervisor"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "editor_headers": build_user_headers("test-editor-1", "Editor"),
}


def make_provider_headers(user_id: str) -> dict:
    """Provider is entity-backed: pass the actual Provider.id whenever the call
    is ownership-gated (uploads, cancel, sign/return/addend, templates, macros)."""
    return build_user_headers(user_id, "Provider")


def make_editor_headers(user_id: str) -> dict:
    """Editor is entity-backed: pass the actual Editor.id whenever the call is
    ownership-gated (claim, submit, release, shift-window declaration)."""
    return build_user_headers(user_id, "Editor")


def make_qa_supervisor_headers(user_id: str) -> dict:
    """QASupervisor is opaque; X-User-ID is recorded as reviewer_user_id but
    never compared to an entity id — except that segregation of duties forbids
    it from equalling the transcript's editor_id (PRD §3.5)."""
    return build_user_headers(user_id, "QASupervisor")
