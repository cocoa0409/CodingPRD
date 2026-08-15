"""Pre-built role headers for every role in the PRD (§2.1).

Transporter is entity-backed: X-User-ID must equal the acting Transporter
record's id, so ownership-gated calls MUST use make_transporter_headers with
the real entity id. RequestingClinician, TransportDispatcher,
HousekeepingStaff, and TransportSupervisor are opaque identities; their shared
constants are canonical, and the make_* builders exist for tests that need a
specific operator id (e.g. segregation-of-duty and own-request checks).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "clinician_headers": build_user_headers("clin-1", "RequestingClinician"),
    "dispatcher_headers": build_user_headers("disp-1", "TransportDispatcher"),
    "housekeeping_headers": build_user_headers("hk-1", "HousekeepingStaff"),
    "supervisor_headers": build_user_headers("sup-1", "TransportSupervisor"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. a Transporter calling a dispatcher-only endpoint).
    "transporter_headers": build_user_headers("test-transporter-1", "Transporter"),
}


def make_clinician_headers(user_id: str = "clin-1") -> dict:
    """For RequestingClinician (opaque). The id is persisted as requested_by
    and gates the own-request cancellation check."""
    return build_user_headers(user_id, "RequestingClinician")


def make_dispatcher_headers(user_id: str = "disp-1") -> dict:
    """For TransportDispatcher (opaque)."""
    return build_user_headers(user_id, "TransportDispatcher")


def make_housekeeping_headers(user_id: str = "hk-1") -> dict:
    """For HousekeepingStaff (opaque). The id is persisted as performed_by
    when the staffer finishes a cleaning task."""
    return build_user_headers(user_id, "HousekeepingStaff")


def make_supervisor_headers(user_id: str = "sup-1") -> dict:
    """For TransportSupervisor (opaque). The id is persisted as verified_by
    when the supervisor verifies a cleaning task."""
    return build_user_headers(user_id, "TransportSupervisor")


def make_transporter_headers(transporter_id: str) -> dict:
    """For Transporter (entity_backed:Transporter). Pass the acting
    Transporter.id whenever the call is ownership-gated (responding to an
    offer, posting trip events, setting own status)."""
    return build_user_headers(transporter_id, "Transporter")
