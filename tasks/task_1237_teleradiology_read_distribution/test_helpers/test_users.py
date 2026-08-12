"""Pre-built role headers for every role in the PRD.

Entity-backed roles (Radiologist, ClientHospitalUser) MUST be built through
the per-instance builders below whenever the call is ownership-gated: the
X-User-ID must equal the backing entity's id, otherwise authentication
fails because the id never resolves to an existing row.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls whose outcome does
# not depend on the caller owning the subject resource (e.g. 400-on-bad-payload
# or 404-on-missing-resource probes).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatch_headers": build_user_headers("test-dispatch-1", "DispatchOps"),
    "qa_headers": build_user_headers("test-qa-1", "QaReviewer"),
    # Fallbacks for entity-backed roles; non-ownership probes only.
    "radiologist_headers": build_user_headers("test-rad-1", "Radiologist"),
    "hospital_user_headers": build_user_headers("test-hosp-1", "ClientHospitalUser"),
}


def make_radiologist_headers(user_id: str) -> dict:
    """Radiologist is entity-backed: pass the real Radiologist.id whenever the
    call is ownership-gated (accept/release/sign/record-notification)."""
    return build_user_headers(user_id, "Radiologist")


def make_hospital_user_headers(user_id: str) -> dict:
    """ClientHospitalUser is entity-backed: pass the real ClientHospital.id
    whenever the call is ownership-gated (study create/cancel, addendum
    request, readback confirm)."""
    return build_user_headers(user_id, "ClientHospitalUser")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatch_headers(user_id: str = "test-dispatch-1") -> dict:
    return build_user_headers(user_id, "DispatchOps")


def make_qa_headers(user_id: str = "test-qa-1") -> dict:
    return build_user_headers(user_id, "QaReviewer")
