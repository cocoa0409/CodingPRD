"""Pre-built role headers for the five VR roles (PRD §2.1).

`VRAdmin` and `FiscalOfficer` carry opaque X-User-ID values (the server never
compares them to any entity id), so a shared constant is the canonical form.

`Counselor`, `Supervisor`, and `Provider` are entity-backed: their X-User-ID is
the id of the acting entity. Ownership-gated calls (a Counselor acting on its
case, a Provider completing its authorization) MUST use the per-instance builder
with the real entity id, else the ownership check rejects every request.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "vradmin_headers": build_user_headers("vradmin-1", "VRAdmin"),
    "fiscal_officer_headers": build_user_headers("fiscal-1", "FiscalOfficer"),
    # Entity-backed roles — shared constants are fallbacks for non-ownership tests only.
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_counselor_headers(counselor_id: str) -> dict:
    """Counselor is entity_backed:Counselor. Pass the real Counselor.id whenever
    the call acts on a case the counselor must own."""
    return build_user_headers(counselor_id, "Counselor")


def make_supervisor_headers(supervisor_id: str) -> dict:
    """Supervisor is entity_backed:Supervisor. The id is recorded (audit) but not
    ownership-gated; any supervisor may approve."""
    return build_user_headers(supervisor_id, "Supervisor")


def make_provider_headers(provider_id: str) -> dict:
    """Provider is entity_backed:Provider. Pass the real Provider.id whenever the
    call reports delivery on the provider's own authorization."""
    return build_user_headers(provider_id, "Provider")
