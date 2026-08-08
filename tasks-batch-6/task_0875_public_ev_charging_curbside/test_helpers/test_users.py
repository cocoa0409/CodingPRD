"""Pre-built role headers for every role in the PRD.

Three roles carry an OPAQUE identity (ProgramAdmin, FieldTechnician, Driver):
X-User-ID is an operator identifier not tied to a persisted entity's id. The
HostOperator role is ENTITY-BACKED against HostSite — X-User-ID must be the id
of the acting HostSite, so any ownership-gated HostOperator call MUST use
make_host_operator_headers(site_id).

Driver identity is opaque, but the server stores X-User-ID as the driver_id on
sessions/reservations and compares that stored value on ownership-gated actions.
A driver acting on its own session/reservation therefore uses
make_driver_headers(driver_id) with the SAME id it created the resource under.

ProgramAdmin identity is opaque, but the four-eyes rule on rebate approval
compares the approver's X-User-ID to submitted_by_user_id, so admin tests build
explicit per-user headers via make_admin_headers(user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "tech_headers": build_user_headers("tech-1", "FieldTechnician"),
    # opaque-role driver fallback — for non-ownership negative tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    # entity-backed HostOperator fallback — for non-ownership negative tests only.
    "host_operator_headers": build_user_headers("test-host-1", "HostOperator"),
}


def admin_headers() -> dict:
    """Default ProgramAdmin credential (user 'admin-1')."""
    return TEST_USERS["admin_headers"]


def make_admin_headers(user_id: str) -> dict:
    """ProgramAdmin (opaque identity, but four-eyes compares this specific id)."""
    return build_user_headers(user_id, "ProgramAdmin")


def tech_headers() -> dict:
    """FieldTechnician (opaque)."""
    return TEST_USERS["tech_headers"]


def make_driver_headers(driver_id: str) -> dict:
    """Driver. Pass the driver_id the session/reservation was created under."""
    return build_user_headers(driver_id, "Driver")


def make_host_operator_headers(site_id: str) -> dict:
    """HostOperator (entity_backed:HostSite). Pass the acting HostSite.id as X-User-ID."""
    return build_user_headers(site_id, "HostOperator")
