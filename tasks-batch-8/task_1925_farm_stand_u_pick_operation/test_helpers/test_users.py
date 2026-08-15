"""Pre-built role headers for every role in the PRD (§2.1).

Every role in this API is opaque: `X-User-ID` is never compared to any entity
id, so the shared constants below are canonical for all calls. `Anonymous` is
the one role for which `X-User-ID` may be omitted entirely, so its constant
carries only the role header.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "gate_staff_headers": build_user_headers("test-gate-staff-1", "GateStaff"),
    "field_staff_headers": build_user_headers("test-field-staff-1", "FieldStaff"),
    "kiosk_device_headers": build_user_headers("test-kiosk-device-1", "KioskDevice"),
    # PRD §2.1: for Anonymous, X-User-ID may be omitted entirely.
    "anonymous_headers": {
        "X-User-Role": "Anonymous",
        "Content-Type": "application/json",
    },
}


def make_farm_manager_headers(user_id: str) -> dict:
    """FarmManager headers with a caller-chosen opaque id."""
    return build_user_headers(user_id, "FarmManager")


def make_gate_staff_headers(user_id: str) -> dict:
    """GateStaff headers with a caller-chosen opaque id."""
    return build_user_headers(user_id, "GateStaff")


def make_field_staff_headers(user_id: str) -> dict:
    """FieldStaff headers with a caller-chosen opaque id."""
    return build_user_headers(user_id, "FieldStaff")


def make_kiosk_device_headers(user_id: str) -> dict:
    """KioskDevice headers with a caller-chosen opaque id."""
    return build_user_headers(user_id, "KioskDevice")
