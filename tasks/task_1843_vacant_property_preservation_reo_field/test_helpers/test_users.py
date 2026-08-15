"""Pre-built role headers for every role in the PRD.

Servicer and FieldCrew identities are entity-backed: their X-User-ID must equal
the id of the Servicer / Crew they act as. Use the per-instance builders with
the real entity id for any ownership-gated call. VendorAdmin, Dispatcher, and
QualityReviewer carry opaque operator identifiers, so shared constants are the
canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "vendor_admin_headers": build_user_headers("test-vendor-admin-1", "VendorAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "quality_reviewer_headers": build_user_headers("test-qa-1", "QualityReviewer"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "servicer_headers": build_user_headers("test-servicer-1", "Servicer"),
    "field_crew_headers": build_user_headers("test-crew-1", "FieldCrew"),
}


def make_servicer_headers(user_id: str) -> dict:
    """For Servicer (entity-backed). Pass the actual Servicer.id as user_id
    whenever the call is ownership-gated (work-order create/cancel, convey,
    bid approve/counter/reject, invoice approve/deny/mark-paid/void)."""
    return build_user_headers(user_id, "Servicer")


def make_field_crew_headers(user_id: str) -> dict:
    """For FieldCrew (entity-backed). Pass the actual Crew.id as user_id
    whenever the call is ownership-gated (start/submit, bid submit/revise/withdraw)
    or stamps the caller identity (damage report, photo upload, bid create)."""
    return build_user_headers(user_id, "FieldCrew")


def make_quality_reviewer_headers(user_id: str) -> dict:
    """For QualityReviewer (opaque id) — use distinct ids for segregation-of-duties
    scenarios where flagger and clearer must differ."""
    return build_user_headers(user_id, "QualityReviewer")


def make_vendor_admin_headers(user_id: str) -> dict:
    """For VendorAdmin (opaque id)."""
    return build_user_headers(user_id, "VendorAdmin")


def make_dispatcher_headers(user_id: str) -> dict:
    """For Dispatcher (opaque id)."""
    return build_user_headers(user_id, "Dispatcher")
