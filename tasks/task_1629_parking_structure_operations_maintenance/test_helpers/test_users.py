"""Pre-built role headers for every role in the PRD.

FacilityManager, ParkingAttendant, RevenueAuditor, MaintenanceSupervisor and
SecurityOfficer are opaque identities: X-User-ID is not tied to any persisted
entity. GateDevice is entity-backed by AccessDevice and MonthlyParker is
entity-backed by ParkerAccount — ownership-gated calls for those roles MUST
use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "facility_manager_headers": build_user_headers("fm-1", "FacilityManager"),
    "parking_attendant_headers": build_user_headers("att-1", "ParkingAttendant"),
    "revenue_auditor_headers": build_user_headers("aud-1", "RevenueAuditor"),
    "maintenance_supervisor_headers": build_user_headers("ms-1", "MaintenanceSupervisor"),
    "security_officer_headers": build_user_headers("sec-1", "SecurityOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "gate_device_headers": build_user_headers("test-gate-device-1", "GateDevice"),
    "monthly_parker_headers": build_user_headers("test-monthly-parker-1", "MonthlyParker"),
}


def make_facility_manager_headers(user_id: str = "fm-1") -> dict:
    return build_user_headers(user_id, "FacilityManager")


def make_parking_attendant_headers(user_id: str) -> dict:
    """ParkingAttendant is opaque, but a shift records the opener's X-User-ID
    as attendant_user_id; close/pay/comp calls must reuse the same id."""
    return build_user_headers(user_id, "ParkingAttendant")


def make_revenue_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RevenueAuditor")


def make_maintenance_supervisor_headers(user_id: str = "ms-1") -> dict:
    return build_user_headers(user_id, "MaintenanceSupervisor")


def make_security_officer_headers(user_id: str = "sec-1") -> dict:
    return build_user_headers(user_id, "SecurityOfficer")


def make_gate_device_headers(device_id: str) -> dict:
    """For GateDevice (entity_backed:AccessDevice). Pass the acting
    AccessDevice.id whenever the call is identity-bound (heartbeat, fault,
    entry, exit)."""
    return build_user_headers(device_id, "GateDevice")


def make_monthly_parker_headers(parker_account_id: str) -> dict:
    """For MonthlyParker (entity_backed:ParkerAccount). Pass the owning
    ParkerAccount.id whenever the call is ownership-gated (report-lost/found,
    withdraw)."""
    return build_user_headers(parker_account_id, "MonthlyParker")
