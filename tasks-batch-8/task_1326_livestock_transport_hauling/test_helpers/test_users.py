"""Pre-built role headers for every role in the PRD (§2.1).

Driver is entity-backed: any ownership-gated call (duty events on own record,
depart/arrive/rest-unload/resume-transit/weather-holds/incidents on the driver's
own load) MUST be made with make_driver_headers(<Driver.id>). The shared
TEST_USERS["driver_headers"] constant is only for calls where the driver's
identity does not gate the outcome (e.g. generic reads or negative tests that
expect ERR_OWNERSHIP_MISMATCH / ERR_FORBIDDEN_ROLE).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CarrierAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # Shared constant for the ComplianceOfficer role; paperwork flows that need
    # two distinct officers (SoD) should use make_compliance_headers("co-1") /
    # make_compliance_headers("co-2") explicitly.
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "consignee_headers": build_user_headers("test-consignee-1", "ConsigneeAgent"),
    "washout_headers": build_user_headers("test-washout-1", "WashoutOperator"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CarrierAdmin")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque, but paperwork verification enforces
    segregation of duties against created_by_user_id — pass a stable id per
    logical officer (e.g. 'co-1' the uploader, 'co-2' the verifier)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_driver_headers(user_id: str) -> dict:
    """Driver is entity-backed. Pass the actual Driver.id whenever the call is
    ownership-gated (duty events on the driver's own record; depart, arrive,
    rest-unload, resume-transit, weather-hold placement/release, and incident
    reports on the driver's own load)."""
    return build_user_headers(user_id, "Driver")


def make_consignee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConsigneeAgent")


def make_washout_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WashoutOperator")
