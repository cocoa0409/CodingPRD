"""Pre-built role headers for every role in the PRD (§2.1).

PharmacyAdmin and DiversionOfficer are opaque roles: X-User-ID is not tied to
any persisted entity, so the shared constants below are their canonical form.

Prescriber, Pharmacist, PharmacyTechnician, and Nurse are entity-backed by
StaffMember: X-User-ID must be the id of an existing, active StaffMember whose
staff_role matches the header. For those roles ALWAYS use the per-instance
builders below with the actual StaffMember id; the shared constants are only
fall-backs for tests that never reach staff resolution.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "PharmacyAdmin"),
    "diversion_officer_headers": build_user_headers(
        "test-diversion-officer-1", "DiversionOfficer"
    ),
    # Entity-backed roles — fall-back only; prefer the make_*_headers builders.
    "prescriber_headers": build_user_headers("test-prescriber-1", "Prescriber"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "technician_headers": build_user_headers("test-technician-1", "PharmacyTechnician"),
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
}


def make_prescriber_headers(user_id: str) -> dict:
    """Prescriber is entity-backed: pass the actual StaffMember.id."""
    return build_user_headers(user_id, "Prescriber")


def make_pharmacist_headers(user_id: str) -> dict:
    """Pharmacist is entity-backed: pass the actual StaffMember.id."""
    return build_user_headers(user_id, "Pharmacist")


def make_technician_headers(user_id: str) -> dict:
    """PharmacyTechnician is entity-backed: pass the actual StaffMember.id."""
    return build_user_headers(user_id, "PharmacyTechnician")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse is entity-backed: pass the actual StaffMember.id."""
    return build_user_headers(user_id, "Nurse")
