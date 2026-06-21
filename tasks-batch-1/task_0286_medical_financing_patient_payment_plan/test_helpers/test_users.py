"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and Anonymous are opaque (X-User-ID not tied to any entity), so the
shared constants are the canonical form. Provider and Patient are entity-backed
(X-User-ID is the Provider.id / PatientAccount.id), so ownership-gated calls MUST
use the per-instance builders make_provider_headers(provider_id) /
make_patient_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles — shared constants are a fallback ONLY for tests that do
    # not exercise ownership (e.g. 403-forbidden-role, 401-unauthenticated). Any
    # ownership-gated call must instead use the builders below with the real entity id.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id as user_id
    whenever the call is ownership-gated (originate/refund/view own purchases)."""
    return build_user_headers(provider_id, "Provider")


def make_patient_headers(account_id: str) -> dict:
    """For Patient (entity_backed:PatientAccount). Pass the actual PatientAccount.id as
    user_id whenever the call is ownership-gated (pay/autopay/close/view own account)."""
    return build_user_headers(account_id, "Patient")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous public surface — limited to submitting a credit application."""
    return build_user_headers(user_id, "Anonymous")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin opaque operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")
